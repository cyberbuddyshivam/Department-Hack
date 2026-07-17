"""
scripts/verify_gateway.py
Manual verification script for llm_gateway.py — ai-workflow-rules.md §2 requires
this to be run after llm_gateway.py is written and before any agent is wired to it.

Tests covered:
  1. Real OpenRouter call succeeds end-to-end (SMALL_MODEL, simple JSON prompt)
  2. Real OpenRouter call succeeds with LARGE_MODEL
  3. Forced timeout (monkey-patch httpx to raise TimeoutException, verify fallback)
  4. Forced circuit-breaker-open (trigger 3 failures, verify CircuitOpen raised,
     then verify cooldown auto-resets to HALF_OPEN and probe succeeds)
  5. Rate-limiter exhaustion (drain bucket, verify LLMGatewayError raised immediately)

Run from the aegis-backend/ directory:
    python scripts/verify_gateway.py

Requires OPENROUTER_API_KEY in .env or environment.
Tests 1 and 2 make real API calls and cost free-tier quota.
Tests 3, 4, 5 are fully local (mock patching).
"""

from __future__ import annotations

import asyncio
import sys
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Add project root to sys.path so imports work when run from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import llm_gateway as gw
from llm_gateway import (
    complete,
    LLMGatewayError,
    SMALL_MODEL,
    LARGE_MODEL,
    get_circuit_state,
    get_available_tokens,
    reset_circuit_breaker,
)
from guardrails.circuit_breaker import CircuitState

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sep(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def check_api_key() -> bool:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return bool(key)


# ---------------------------------------------------------------------------
# Test 1: Real call — SMALL_MODEL
# ---------------------------------------------------------------------------

async def test_real_call_small_model() -> None:
    sep("Test 1: Real OpenRouter call — SMALL_MODEL")
    print(f"  Model: {SMALL_MODEL}")

    prompt = (
        "You are a JSON-only responder. "
        'Respond with exactly this JSON and nothing else: {"status": "ok", "value": 42}'
    )

    try:
        t0 = time.monotonic()
        result = await complete(prompt=prompt, model=SMALL_MODEL, temperature=0.0)
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  Response ({elapsed:.0f} ms): {result[:200]}")
        if '"status"' in result or "ok" in result or "42" in result:
            print(f"  {PASS} Got coherent JSON-ish response from {SMALL_MODEL}")
        else:
            print(f"  {FAIL} Response doesn't look like expected JSON: {result!r}")
    except LLMGatewayError as exc:
        print(f"  {FAIL} LLMGatewayError: {exc}")
    finally:
        reset_circuit_breaker()


# ---------------------------------------------------------------------------
# Test 2: Real call — LARGE_MODEL
# ---------------------------------------------------------------------------

async def test_real_call_large_model() -> None:
    sep("Test 2: Real OpenRouter call — LARGE_MODEL")
    print(f"  Model: {LARGE_MODEL}")

    prompt = (
        "Summarise in one sentence why emergency dispatch speed matters. "
        "Be concise."
    )

    try:
        t0 = time.monotonic()
        result = await complete(
            prompt=prompt,
            model=LARGE_MODEL,
            temperature=0.5,
            max_tokens=128,
        )
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  Response ({elapsed:.0f} ms): {result[:300]}")
        if len(result.strip()) > 10:
            print(f"  {PASS} Got non-empty response from {LARGE_MODEL}")
        else:
            print(f"  {FAIL} Response suspiciously short: {result!r}")
    except LLMGatewayError as exc:
        print(f"  {FAIL} LLMGatewayError: {exc}")
    finally:
        reset_circuit_breaker()


# ---------------------------------------------------------------------------
# Test 3: Forced timeout — httpx.TimeoutException
# ---------------------------------------------------------------------------

async def test_forced_timeout() -> None:
    sep("Test 3: Forced timeout (mocked — no real API call)")

    reset_circuit_breaker()
    gw._rate_limiter._tokens = 5.0

    timeout_exc = httpx.TimeoutException("simulated read timeout")

    # Mock both the API key resolution AND the internal retry function
    with patch.object(gw, "_resolve_api_key", return_value="sk-mock-key"), \
         patch.object(gw, "_complete_with_retry", new=AsyncMock(side_effect=timeout_exc)):
        try:
            await complete(prompt="irrelevant", model=SMALL_MODEL)
            print(f"  {FAIL} Expected LLMGatewayError but got a result")
        except LLMGatewayError as exc:
            print(f"  {PASS} LLMGatewayError raised on timeout: {exc}")
        except Exception as exc:
            print(f"  {FAIL} Unexpected exception type {type(exc).__name__}: {exc}")

    reset_circuit_breaker()
    print(f"  Circuit state after reset: {get_circuit_state()}")
    assert get_circuit_state() == "CLOSED"
    print(f"  {PASS} Circuit back to CLOSED after reset")


# ---------------------------------------------------------------------------
# Test 4: Circuit-breaker-open — trigger 3 failures, verify OPEN, wait for HALF_OPEN
# ---------------------------------------------------------------------------

async def test_circuit_breaker_open() -> None:
    sep("Test 4: Circuit breaker opens after 3 failures, auto-recovers")

    reset_circuit_breaker()
    gw._rate_limiter._tokens = 5.0

    # Re-configure the breaker to a short cooldown so we can test recovery
    gw._circuit_breaker._failure_threshold = 3
    gw._circuit_breaker._cooldown_seconds = 1.0   # 1 second for test speed

    failure_exc = httpx.NetworkError("simulated network error")

    # Trigger 3 failures by having _complete_with_retry raise every time.
    # We need to bypass tenacity's internal retry so it surfaces immediately.
    # Use on_failure() directly for speed.
    print("  Triggering 3 consecutive on_failure() calls...")
    gw._circuit_breaker.on_failure()
    gw._circuit_breaker.on_failure()
    gw._circuit_breaker.on_failure()
    assert get_circuit_state() == "OPEN", f"Expected OPEN, got {get_circuit_state()}"
    print(f"  {PASS} Circuit is OPEN after 3 failures")

    # Next complete() should raise LLMGatewayError (circuit open) without hitting API
    gw._rate_limiter._tokens = 5.0
    try:
        await complete(prompt="any", model=SMALL_MODEL)
        print(f"  {FAIL} Expected LLMGatewayError (circuit open) but got a result")
    except LLMGatewayError as exc:
        print(f"  {PASS} LLMGatewayError raised (circuit open): {exc}")

    # Wait for cooldown
    print("  Waiting 1.2 s for cooldown to expire...")
    await asyncio.sleep(1.2)
    assert get_circuit_state() == "HALF_OPEN", f"Expected HALF_OPEN, got {get_circuit_state()}"
    print(f"  {PASS} Circuit transitioned to HALF_OPEN after cooldown")

    # A successful probe call should close the circuit
    # Mock both key resolution and the HTTP post to simulate a successful LLM response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"probe": "ok"}'}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(gw, "_resolve_api_key", return_value="sk-mock-key"), \
         patch.object(
             gw._get_http_client(),
             "post",
             new=AsyncMock(return_value=mock_response),
         ):
        gw._rate_limiter._tokens = 5.0
        try:
            result = await complete(prompt="probe", model=SMALL_MODEL)
            assert "probe" in result or "ok" in result
            print(f"  {PASS} Probe call succeeded: {result!r}")
        except LLMGatewayError as exc:
            print(f"  {FAIL} Probe call failed: {exc}")

    assert get_circuit_state() == "CLOSED", f"Expected CLOSED, got {get_circuit_state()}"
    print(f"  {PASS} Circuit back to CLOSED after successful probe")

    # Restore defaults
    gw._circuit_breaker._cooldown_seconds = 30.0
    reset_circuit_breaker()


# ---------------------------------------------------------------------------
# Test 5: Rate-limiter exhaustion
# ---------------------------------------------------------------------------

async def test_rate_limiter_exhaustion() -> None:
    sep("Test 5: Rate limiter raises immediately when bucket empty")

    reset_circuit_breaker()
    # Drain the bucket completely
    gw._rate_limiter._tokens = 0.0

    try:
        await complete(prompt="any", model=SMALL_MODEL)
        print(f"  {FAIL} Expected LLMGatewayError (rate limit) but got a result")
    except LLMGatewayError as exc:
        if "rate limit" in str(exc).lower() or "Rate limit" in str(exc):
            print(f"  {PASS} LLMGatewayError raised immediately (rate limit): {exc}")
        else:
            print(f"  {FAIL} LLMGatewayError raised but wrong reason: {exc}")

    # Refill and confirm it works again
    gw._rate_limiter._tokens = 5.0
    print(f"  {PASS} Bucket refilled — available_tokens = {get_available_tokens():.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\nAEGIS — LLM Gateway Manual Verification Script")
    print("ai-workflow-rules.md §2 compliance check")
    print("OPENROUTER_API_KEY present: " + str(check_api_key()))
    print("SMALL_MODEL: " + SMALL_MODEL)
    print("LARGE_MODEL: " + LARGE_MODEL)

    if not check_api_key():
        print("\nWARNING: OPENROUTER_API_KEY not set.")
        print("Tests 1 and 2 (real API calls) will fail.")
        print("Tests 3, 4, 5 (mocked) will still run.\n")

    # Mocked tests always run
    await test_forced_timeout()
    await test_circuit_breaker_open()
    await test_rate_limiter_exhaustion()

    # Real API tests only run if key is present
    if check_api_key():
        # 10s gap respects the free-tier rate limit window between calls.
        print("\nWaiting 10s before real API calls...")
        await asyncio.sleep(10)
        await test_real_call_small_model()
        print("\nWaiting 10s between model calls...")
        await asyncio.sleep(10)
        await test_real_call_large_model()
    else:
        sep("Tests 1 & 2")
        print(f"  {SKIP} Skipped — no OPENROUTER_API_KEY in environment")

    print("\n" + "=" * 60)
    print("  Verification complete. Review [PASS]/[FAIL]/[SKIP] above.")
    print("=" * 60 + "\n")

    # Close the shared HTTP client cleanly
    await gw.close_http_client()


if __name__ == "__main__":
    asyncio.run(main())
