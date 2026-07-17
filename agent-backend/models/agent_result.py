"""
models/agent_result.py
Shared AgentResult base model — every agent in the pipeline returns exactly
this shape, with a typed generic `result` field so callers get full type safety
without casting.

Generic usage example:
    result: AgentResult[TriageOutput] = await run_triage_agent(...)
    score: int = result.result.severity_score  # fully typed

Invariants (from architecture.md §4):
- `source` is always "llm" on the happy path, "fallback" on any failure.
- `confidence` < 0.5 on a fallback result; this signals the orchestrator to
  set `requires_human_review: true` on FinalOutput.
- `latency_ms` is wall-clock time measured by the agent itself (not network only).
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class AgentResult(BaseModel, Generic[T]):
    """
    Universal envelope returned by every agent.

    Type parameter T is the agent-specific result model (e.g. TriageOutput,
    DispatchOutput). Using Generic[T] lets the orchestrator unpack result
    with full static type information.
    """

    agent_name: str = Field(
        description="Canonical name of the agent that produced this result, "
        "e.g. 'triage', 'verifier', 'dispatch'."
    )
    result: T = Field(
        description="Agent-specific typed output. Schema differs per agent."
    )
    reasoning: str = Field(
        description="Free-text explanation of how the agent reached its result. "
        "Populated from the LLM's chain-of-thought on the happy path, "
        "or from the fallback rule description on the fallback path."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Agent's self-reported confidence in its result, 0–1. "
            "Values < 0.5 trigger requires_human_review on FinalOutput. "
            "Fallback results must set confidence ≤ 0.4."
        ),
    )
    source: Literal["llm", "fallback"] = Field(
        description=(
            "'llm' when the result came from a successful OpenRouter call; "
            "'fallback' when the LLM call failed or the circuit breaker was open."
        )
    )
    latency_ms: float = Field(
        ge=0.0,
        description="Wall-clock time in milliseconds the agent took to produce its result.",
    )
