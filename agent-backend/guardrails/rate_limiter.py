"""
guardrails/rate_limiter.py
Token-bucket rate limiter — shared across all agents via the LLM Gateway.

Design:
- Classic token-bucket algorithm: bucket fills at a constant rate (tokens/sec),
  up to a maximum capacity (burst allowance).
- `acquire()` deducts one token. If no token is available it raises
  `RateLimitExceeded` immediately (no blocking sleep) so the LLM Gateway can
  route to the agent's fallback without hanging the request.
- All state is in-memory; no external service needed at this scale.
- Bucket sizing is conservative for OpenRouter free tier:
    OpenRouter free tier: ~20 requests/minute = 0.333 req/sec sustained.
    We use 0.3 req/sec refill rate (slightly under limit) and burst=5
    so a brief flurry of parallel agent calls doesn't get rejected while still
    preventing sustained overuse that would get the key throttled.

Thread-safety / async note:
  FastAPI runs a single asyncio event loop. Because Python's asyncio is
  cooperative (not truly parallel), `_refill()` and `acquire()` are never
  interrupted mid-execution by another coroutine — no locks needed.
  If multiple uvicorn workers are added later, replace with a Redis-backed
  bucket (e.g. redis-py's INCR + EXPIRE pattern).

Usage:
    from guardrails.rate_limiter import RateLimiter, RateLimitExceeded

    limiter = RateLimiter()           # one instance shared by llm_gateway.py
    try:
        limiter.acquire()
    except RateLimitExceeded:
        # route to agent fallback
        ...
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """
    Raised by RateLimiter.acquire() when the bucket is empty.
    The LLM Gateway catches this and routes the agent to its fallback path.
    """


class RateLimiter:
    """
    Token-bucket rate limiter.

    Parameters
    ----------
    refill_rate : float
        Tokens added per second. Default: 0.3 (= 18 req/min, safely under
        OpenRouter free-tier limit of ~20 req/min).
    capacity : float
        Maximum tokens the bucket can hold (burst allowance). Default: 5.
        Allows up to 5 parallel agent calls to start immediately after a
        quiet period, then settles back to the sustained rate.
    """

    def __init__(
        self,
        refill_rate: float = 0.3,
        capacity: float = 5.0,
    ) -> None:
        if refill_rate <= 0:
            raise ValueError(f"refill_rate must be positive, got {refill_rate}")
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")

        self._refill_rate: float = refill_rate
        self._capacity: float = capacity
        self._tokens: float = capacity          # start full so first calls go through
        self._last_refill_time: float = time.monotonic()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """
        Consume one token from the bucket.

        Raises
        ------
        RateLimitExceeded
            If the bucket is currently empty. The caller should route to
            the agent's deterministic fallback immediately.
        """
        self._refill()
        if self._tokens < 1.0:
            logger.warning(
                "RateLimiter: bucket empty (%.2f tokens). Raising RateLimitExceeded.",
                self._tokens,
            )
            raise RateLimitExceeded(
                f"LLM Gateway rate limit exceeded. "
                f"Current tokens: {self._tokens:.2f}, "
                f"refill rate: {self._refill_rate}/s."
            )
        self._tokens -= 1.0
        logger.debug(
            "RateLimiter: token consumed. Remaining: %.2f / %.0f.",
            self._tokens,
            self._capacity,
        )

    @property
    def available_tokens(self) -> float:
        """Return current token count after a refill (read-only, for testing/observability)."""
        self._refill()
        return self._tokens

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """
        Add tokens proportional to elapsed time since last refill.
        Called internally before every acquire() and status check.
        """
        now: float = time.monotonic()
        elapsed: float = now - self._last_refill_time
        added: float = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._capacity, self._tokens + added)
            self._last_refill_time = now
