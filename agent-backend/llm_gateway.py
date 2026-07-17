"""
llm_gateway.py
Single chokepoint for all LLM calls in AEGIS.

Every agent calls `gateway.complete(...)` — nothing calls OpenRouter directly.
This file is where rate limiting, circuit breaking, retries, and the actual
HTTP call all live.

Architecture invariants enforced here (from architecture.md §4):
- Every agent call goes through this gateway, never OpenRouter directly.
- Rate limiter, circuit breaker, and retry are applied in this order:
    1. Rate limiter  → RateLimitExceeded  → agent fallback
    2. Circuit breaker → CircuitOpen       → agent fallback
    3. tenacity retry  → RetryError        → agent fallback
    4. httpx call      → HTTP / parse err  → on_failure() + retry
- The gateway raises LLMGatewayError for any unrecoverable failure.
  Agents catch LLMGatewayError and return their deterministic fallback result.
- Nothing in this file is synchronous/blocking.

Model IDs (locked from Step 3 model selection):
  SMALL_MODEL: cohere/north-mini-code:free
    - 3B active / 30B total params, JSON schema support, 256K context
    - Used by: Triage, Verifier, Classifier agents
  LARGE_MODEL: nvidia/nemotron-3-ultra:free
    - 55B active / 550B total params, deep reasoning, 1M context
    - Used by: Admission Formalities agent (human-readable brief generation)

Tenacity retry config (from architecture.md §5):
  max_attempts = 2  (1 retry — this is transport-level, not logic-level)
  wait         = exponential backoff with jitter (min 0.5s, max 10s)
  retry on     = httpx.HTTPStatusError (5xx), httpx.TimeoutException,
                 httpx.NetworkError, json.JSONDecodeError
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    RetryError,
    before_sleep_log,
)

from guardrails.rate_limiter import RateLimiter, RateLimitExceeded
from guardrails.circuit_breaker import CircuitBreaker, CircuitOpen

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model IDs (locked from live openrouter.ai/api/v1/models check — 2026-07-16)
# ---------------------------------------------------------------------------

SMALL_MODEL: str = "meta-llama/llama-3.1-8b-instruct"
"""Fast model for structured JSON output: Triage, Verifier, Classifier.
Meta Llama 3.1 8B Instruct — plain instruct, JSON mode support."""

LARGE_MODEL: str = "meta-llama/llama-3.1-8b-instruct"
"""Reasoning model for the human-readable brief: Admission Formalities."""

# ---------------------------------------------------------------------------
# OpenRouter API constants
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_ENDPOINT: str = f"{OPENROUTER_BASE_URL}/chat/completions"

# Site metadata sent with every request (OpenRouter convention)
_SITE_URL: str = "https://github.com/aegis-dispatch"
_SITE_NAME: str = "AEGIS"

# Per-request timeout in seconds (separate from the per-agent 6s orchestrator timeout)
# This is the *network* timeout — the orchestrator's asyncio.wait_for is the hard cap.
_HTTP_TIMEOUT_SECONDS: float = 12.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMGatewayError(Exception):
    """
    Raised when all retry attempts are exhausted or a non-retryable error occurs.
    Every agent must catch this and return its deterministic fallback result.
    """


# ---------------------------------------------------------------------------
# Singleton guardrail instances (shared across all agents for the process lifetime)
# ---------------------------------------------------------------------------

_rate_limiter: RateLimiter = RateLimiter(
    refill_rate=5.0,
    capacity=100.0,
)

_circuit_breaker: CircuitBreaker = CircuitBreaker(
    failure_threshold=3,    # opens after 3 consecutive failures
    cooldown_seconds=30.0,  # stays open for 30 s
)

# Shared async HTTP client — created once, reused across all calls (connection pooling)
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient, creating it on first call."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=_HTTP_TIMEOUT_SECONDS,
                write=5.0,
                pool=5.0,
            ),
            headers={
                "HTTP-Referer": _SITE_URL,
                "X-Title": _SITE_NAME,
            },
        )
    return _http_client


async def close_http_client() -> None:
    """Close the shared client gracefully. Call on app shutdown."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
        logger.info("LLMGateway: HTTP client closed.")


# ---------------------------------------------------------------------------
# Core gateway function
# ---------------------------------------------------------------------------

async def complete(
    *,
    prompt: str,
    model: str = SMALL_MODEL,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """
    Send a completion request to OpenRouter and return the raw response text.

    Agents call this function with a fully-constructed prompt (including the
    JSON schema instruction). The return value is a raw string; agents parse
    it with `model_validate_json()`.

    Parameters
    ----------
    prompt : str
        The user-turn message. Must already have caller-supplied text
        sanitized via guardrails.sanitizer.sanitize().
    model : str
        OpenRouter model ID. Use SMALL_MODEL or LARGE_MODEL constants.
        Default: SMALL_MODEL.
    system_prompt : str | None
        Optional system turn. When provided, sent as the first message with
        role="system". When None, no system message is added.
    temperature : float
        Sampling temperature. Default: 0.2 for structured JSON outputs
        (low = more deterministic). Use higher for the human brief.
    max_tokens : int
        Maximum output tokens. Default: 1024 (enough for all agent schemas).

    Returns
    -------
    str
        The raw text content from the model's first choice. Agents are
        responsible for parsing this as JSON.

    Raises
    ------
    LLMGatewayError
        If rate limited, circuit is open, or all retries are exhausted.
        Agents catch this and return their fallback result.
    """
    # Guard 1: Rate limiter — fail fast, never block
    try:
        _rate_limiter.acquire()
    except RateLimitExceeded as exc:
        logger.warning("LLMGateway: rate limit exceeded — raising LLMGatewayError.")
        raise LLMGatewayError(f"Rate limit exceeded: {exc}") from exc

    # Guard 2: Circuit breaker — fail fast if open
    try:
        _circuit_breaker.before_call()
    except CircuitOpen as exc:
        logger.warning("LLMGateway: circuit open — raising LLMGatewayError.")
        raise LLMGatewayError(f"Circuit breaker open: {exc}") from exc

    # Resolve API key only after guardrails pass (avoids env lookup on fast-fail paths)
    api_key: str = _resolve_api_key()

    # Guards 3+: Retry wrapper (transport-level — max 2 attempts)
    start_ms: float = time.monotonic() * 1000

    try:
        result: str = await _complete_with_retry(
            api_key=api_key,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _circuit_breaker.on_success()
        elapsed_ms = time.monotonic() * 1000 - start_ms
        logger.info(
            "LLMGateway: success — model=%s, %.0f ms.", model, elapsed_ms
        )
        return result

    except RetryError as exc:
        _circuit_breaker.on_failure()
        logger.error(
            "LLMGateway: all retry attempts exhausted for model=%s.", model
        )
        raise LLMGatewayError(
            f"All retry attempts exhausted for model '{model}'."
        ) from exc

    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
        # Non-retried transport errors that escaped tenacity (shouldn't happen normally)
        _circuit_breaker.on_failure()
        logger.error("LLMGateway: unretried transport error: %s", exc)
        raise LLMGatewayError(f"Transport error: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal: tenacity-wrapped HTTP call
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(
        (
            httpx.HTTPStatusError,    # 5xx from OpenRouter
            httpx.TimeoutException,   # read/connect timeout
            httpx.NetworkError,       # connection refused, DNS failure
            json.JSONDecodeError,     # malformed response body
        )
    ),
    stop=stop_after_attempt(2),   # max 2 attempts (1 retry)
    wait=wait_exponential_jitter(initial=0.5, max=10.0, jitter=1.0),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,  # let tenacity wrap in RetryError for the outer handler
)
async def _complete_with_retry(
    *,
    api_key: str,
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    temperature: float,
    max_tokens: int,
) -> str:
    """
    Single HTTP attempt to OpenRouter. Decorated with tenacity for retry.

    Raises the original exception on failure so tenacity can decide whether
    to retry. The outer `complete()` counts failures against the circuit breaker.
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    client = _get_http_client()
    response = await client.post(
        OPENROUTER_CHAT_ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    # Raise for 4xx/5xx so tenacity can retry on 5xx
    if response.status_code >= 500:
        response.raise_for_status()

    if response.status_code == 429:
        # 429 = rate limited by OpenRouter — retry
        logger.warning("LLMGateway: 429 Too Many Requests from OpenRouter.")
        response.raise_for_status()

    if response.status_code >= 400:
        # 4xx (except 429) = client error — do not retry, raise immediately
        logger.error(
            "LLMGateway: client error %d: %s",
            response.status_code,
            response.text[:200],
        )
        response.raise_for_status()

    body: dict[str, Any] = response.json()   # raises JSONDecodeError on bad body

    try:
        content: str = body["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError) as exc:
        raise json.JSONDecodeError(
            f"Unexpected OpenRouter response shape: {list(body.keys())}",
            doc=str(body),
            pos=0,
        ) from exc

    return content


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_api_key() -> str:
    """
    Read OPENROUTER_API_KEY from the environment.

    Raises
    ------
    LLMGatewayError
        If the key is not set — fail early with a clear message rather than
        sending an empty Authorization header.
    """
    key: str = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise LLMGatewayError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Copy .env.example to .env and add your key."
        )
    return key


# ---------------------------------------------------------------------------
# Observability helpers (used by agents and tests)
# ---------------------------------------------------------------------------

def get_circuit_state() -> str:
    """Return the current circuit breaker state name (CLOSED/OPEN/HALF_OPEN)."""
    return _circuit_breaker.state.name


def get_available_tokens() -> float:
    """Return the current rate-limiter token count (for observability)."""
    return _rate_limiter.available_tokens


def reset_circuit_breaker() -> None:
    """
    Force-reset the circuit breaker to CLOSED. For use in tests only.
    Never call this in production code.
    """
    _circuit_breaker.on_success()
    logger.warning("LLMGateway: circuit breaker manually reset (test use only).")
