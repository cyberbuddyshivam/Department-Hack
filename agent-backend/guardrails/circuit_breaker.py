"""
guardrails/circuit_breaker.py
Simple in-process circuit breaker around the LLM Gateway.

Behaviour (from architecture.md §5):
- CLOSED  → normal operation; all calls go through.
- OPEN    → opened after `failure_threshold` consecutive failures;
             all calls immediately raise CircuitOpen (→ agent fallback).
             The breaker stays OPEN for `cooldown_seconds`.
- HALF-OPEN → after the cooldown window expires, the next call is allowed
              through as a probe. If it succeeds, the breaker resets to CLOSED.
              If it fails, the breaker returns to OPEN with a fresh cooldown.

Locked parameters from architecture.md:
  failure_threshold = 3   (open after 3 consecutive failures)
  cooldown_seconds  = 30  (stay open for 30 s)

Usage:
    from guardrails.circuit_breaker import CircuitBreaker, CircuitOpen

    breaker = CircuitBreaker()    # one instance shared by llm_gateway.py

    with breaker:
        # make LLM call here
        response = await call_openrouter(...)

    # OR manually:
    try:
        breaker.before_call()
        # ... make LLM call ...
        breaker.on_success()
    except SomeLLMError:
        breaker.on_failure()
        raise
"""

from __future__ import annotations

import logging
import time
from enum import Enum, auto
from types import TracebackType
from typing import Optional, Type

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()     # healthy — calls go through
    OPEN = auto()       # unhealthy — all calls rejected immediately
    HALF_OPEN = auto()  # recovery probe — one call allowed through


class CircuitOpen(Exception):
    """
    Raised when the circuit breaker is OPEN.
    The LLM Gateway catches this and routes the agent to its fallback path.
    """


class CircuitBreaker:
    """
    Three-state circuit breaker.

    Parameters
    ----------
    failure_threshold : int
        Consecutive failures required to open the circuit. Default: 3.
    cooldown_seconds : float
        Seconds to stay in OPEN state before allowing a probe. Default: 30.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1, got {failure_threshold}")
        if cooldown_seconds <= 0:
            raise ValueError(f"cooldown_seconds must be positive, got {cooldown_seconds}")

        self._failure_threshold: int = failure_threshold
        self._cooldown_seconds: float = cooldown_seconds

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._opened_at: Optional[float] = None  # monotonic timestamp when breaker opened

    # ------------------------------------------------------------------
    # Public state API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return the current state, transitioning OPEN→HALF_OPEN if cooldown elapsed."""
        if self._state is CircuitState.OPEN:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self._cooldown_seconds:
                    logger.info(
                        "CircuitBreaker: cooldown elapsed (%.1fs). Transitioning OPEN→HALF_OPEN.",
                        elapsed,
                    )
                    self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def is_closed(self) -> bool:
        return self.state is CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state is CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state is CircuitState.HALF_OPEN

    # ------------------------------------------------------------------
    # Call lifecycle hooks (used by llm_gateway.py)
    # ------------------------------------------------------------------

    def before_call(self) -> None:
        """
        Must be called before each LLM attempt.

        Raises
        ------
        CircuitOpen
            If the breaker is currently OPEN (cooldown not yet elapsed).
            The LLM Gateway catches this and routes to fallback.
        """
        current = self.state   # property handles OPEN→HALF_OPEN transition
        if current is CircuitState.OPEN:
            remaining = 0.0
            if self._opened_at is not None:
                remaining = max(
                    0.0,
                    self._cooldown_seconds - (time.monotonic() - self._opened_at),
                )
            logger.warning(
                "CircuitBreaker: OPEN — rejecting call. Cooldown remaining: %.1fs.",
                remaining,
            )
            raise CircuitOpen(
                f"Circuit breaker is OPEN. "
                f"Cooldown remaining: {remaining:.1f}s. "
                f"Route to agent fallback."
            )
        if current is CircuitState.HALF_OPEN:
            logger.info("CircuitBreaker: HALF_OPEN — allowing probe call through.")

    def on_success(self) -> None:
        """
        Call after a successful LLM response.
        Resets the failure counter and closes the circuit.
        """
        if self._state is not CircuitState.CLOSED:
            logger.info(
                "CircuitBreaker: success — transitioning %s→CLOSED.", self._state.name
            )
        self._consecutive_failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED

    def on_failure(self) -> None:
        """
        Call after any LLM failure (timeout, HTTP error, parse error).
        Increments the consecutive failure counter; opens the circuit if
        the threshold is reached.
        """
        self._consecutive_failures += 1
        logger.warning(
            "CircuitBreaker: failure #%d / %d threshold.",
            self._consecutive_failures,
            self._failure_threshold,
        )
        if self._consecutive_failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.error(
                "CircuitBreaker: threshold reached — circuit OPEN. "
                "Cooldown: %.0fs. All calls will go to fallback.",
                self._cooldown_seconds,
            )

    # ------------------------------------------------------------------
    # Context manager support (optional convenience)
    # ------------------------------------------------------------------

    def __enter__(self) -> "CircuitBreaker":
        self.before_call()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        if exc_type is None:
            self.on_success()
        else:
            # Only count genuine LLM/transport failures, not CircuitOpen itself.
            if not issubclass(exc_type, CircuitOpen):
                self.on_failure()
        return False   # never suppress the exception
