"""
agents/verifier.py
AEGIS — Verifier Agent (Step 6 in build order)

Responsibility:
  Double-check the Triage Agent's severity score. Outputs agreement or disagreement.
  If it disagrees, it suggests an alternative score. The actual retry loop is
  handled by the orchestrator, not here.

Contract (from architecture.md §4):
  Input:  VerifierInput (contains the text and the triage score)
  Output: AgentResult[VerifierOutput]
  Fallback trigger: LLM call fails (LLMGatewayError) → returns VerifierOutput with
                    agrees=True, source="fallback", confidence≤0.4. (We default to
                    agreeing so we don't force a retry loop on a network error, but
                    the low confidence guarantees human review).

Prompt design:
  Asks the model for a JSON object with agrees (bool) and recommended_score (int/null).
  We use SMALL_MODEL.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from llm_gateway import complete, LLMGatewayError, SMALL_MODEL
from models.agent_result import AgentResult

logger = logging.getLogger(__name__)

AGENT_NAME = "verifier"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VerifierInput(BaseModel):
    """
    Input for the Verifier Agent. Needs the incident text and the triage score.
    """
    incident_id: str = Field(description="Used for logging and traceability.")
    consolidated_text: str = Field(description="The clean, merged incident description.")
    triage_severity_score: int = Field(description="The severity score (1-10) assigned by the Triage Agent.")


class VerifierOutput(BaseModel):
    """
    Agent-specific typed output for Verifier.
    """
    agrees: bool = Field(description="True if the verifier agrees with the triage score, False otherwise.")
    recommended_score: Optional[int] = Field(
        default=None,
        description="If disagrees, the score (1-10) the verifier believes is correct."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(input_data: VerifierInput) -> AgentResult[VerifierOutput]:
    """
    Verify the Triage Agent's severity score.

    Parameters
    ----------
    input_data : VerifierInput
        Contains the incident text and the triage score to verify.

    Returns
    -------
    AgentResult[VerifierOutput]
        Always returns a result. On LLM failure, returns a fallback result
        agreeing with the score but with low confidence.
    """
    t_start = time.monotonic()
    
    prompt = (
        "You are an expert medical dispatcher acting as a secondary reviewer. "
        "Review the incident description and the preliminary severity score (1-10) assigned by the primary triage.\n\n"
        "Severity Scale Guidelines:\n"
        "1-3: Minor injuries, non-urgent, stable condition.\n"
        "4-6: Urgent, moderate injuries or illness, but stable.\n"
        "7-8: Emergency, potentially life-threatening or severe pain.\n"
        "9-10: Critical, immediately life-threatening, requires immediate advanced life support.\n\n"
        f"Incident Description:\n\"{input_data.consolidated_text}\"\n\n"
        f"Preliminary Severity Score: {input_data.triage_severity_score}\n\n"
        "Do you agree with this score? Respond with ONLY a JSON object in this exact format and nothing else:\n"
        '{"agrees": <bool>, "recommended_score": <int 1-10 or null if agrees>, '
        '"confidence": <0.0-1.0>, "reasoning": "<1-2 sentences explaining why>"}'
    )

    try:
        raw = await complete(
            prompt=prompt,
            model=SMALL_MODEL,
            temperature=0.0,
            max_tokens=150,
        )

        parsed = _parse_llm_response(raw)
        if parsed is None:
            raise ValueError(f"Could not parse LLM response: {raw!r}")

        agrees = parsed.get("agrees")
        if not isinstance(agrees, bool):
            raise ValueError(f"Invalid 'agrees' value: {agrees}")

        recommended_score = parsed.get("recommended_score")
        if not agrees:
            if not isinstance(recommended_score, int) or not (1 <= recommended_score <= 10):
                raise ValueError(f"Invalid recommended_score on disagreement: {recommended_score}")
        else:
            # If they agree, we ignore recommended_score even if they provided one
            recommended_score = None

        llm_confidence = float(parsed.get("confidence", 0.5))
        llm_reasoning = str(parsed.get("reasoning", "LLM verified severity."))

        output = VerifierOutput(
            agrees=agrees,
            recommended_score=recommended_score
        )
        
        confidence = min(llm_confidence, 0.95)
        source = "llm"
        reasoning = llm_reasoning

    except LLMGatewayError as exc:
        logger.warning(
            "VerifierAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "VerifierAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"Parse error: {exc}")

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "VerifierAgent: %s | agrees=%s | rec=%s | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id,
        output.agrees,
        output.recommended_score,
        source,
        confidence,
        latency_ms,
    )

    return AgentResult(
        agent_name=AGENT_NAME,
        result=output,
        reasoning=reasoning,
        confidence=confidence,
        source=source,  # type: ignore[arg-type]
        latency_ms=round(latency_ms, 1),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fallback_result(reason: str) -> tuple[VerifierOutput, str, str, float]:
    """
    Fallback when Verifier LLM fails.
    Defaults to agreeing (so we don't trigger unnecessary retries on network errors).
    Confidence=0.3 ensures it will be flagged for human review.
    """
    output = VerifierOutput(agrees=True, recommended_score=None)
    reasoning = (
        f"Verifier evaluation failed ({reason}). "
        "Defaulted to agreement to proceed pipeline. "
        "Human review required."
    )
    return output, reasoning, "fallback", 0.3


def _parse_llm_response(raw: str) -> Optional[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    json_str = text[brace_start: brace_end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None
