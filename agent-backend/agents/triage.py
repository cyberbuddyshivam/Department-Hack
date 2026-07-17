"""
agents/triage.py
AEGIS — Triage Agent (Step 5 in build order)

Responsibility:
  Assess the medical severity of an incident based on the consolidated text.
  Outputs a severity score from 1 to 10.

Contract (from architecture.md §4):
  Input:  TriageInput (contains only the text needed, not the full IntakeOutput)
  Output: AgentResult[TriageOutput]
  Fallback trigger: LLM call fails (LLMGatewayError) → returns TriageOutput with
                    severity_score=5, source="fallback", confidence≤0.4

Prompt design:
  Asks the model for a JSON object with severity_score, reasoning, and confidence.
  We use SMALL_MODEL (fast, structured JSON outputs).
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

AGENT_NAME = "triage"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TriageInput(BaseModel):
    """
    Input subset required by the Triage Agent.
    Obeys architecture.md rule: "No agent receives the full incident blob if it only needs a slice".
    """
    incident_id: str = Field(description="Used for logging and traceability.")
    consolidated_text: str = Field(
        description="The clean, merged incident description from the Intake Agent."
    )


class TriageOutput(BaseModel):
    """
    Agent-specific typed output for Triage.
    """
    severity_score: int = Field(
        ge=1,
        le=10,
        description="Assessed severity score from 1 (minor) to 10 (life-threatening)."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(input_data: TriageInput) -> AgentResult[TriageOutput]:
    """
    Assess severity of the incident.

    Parameters
    ----------
    input_data : TriageInput
        Contains the incident text to be evaluated.

    Returns
    -------
    AgentResult[TriageOutput]
        Always returns a result. On LLM failure or parse error, returns a
        fallback result with severity_score=5, source="fallback", confidence=0.3.
    """
    t_start = time.monotonic()
    
    prompt = (
        "You are an expert emergency medical dispatcher. Your job is to triage an incident "
        "description and assign a medical severity score from 1 to 10.\n\n"
        "Severity Scale Guidelines:\n"
        "1-3: Minor injuries, non-urgent, stable condition (e.g. sprains, minor cuts).\n"
        "4-6: Urgent, moderate injuries or illness, but stable (e.g. broken bone, fever).\n"
        "7-8: Emergency, potentially life-threatening or severe pain (e.g. chest pain, major trauma, bleeding).\n"
        "9-10: Critical, immediately life-threatening, requires immediate advanced life support (e.g. cardiac arrest, unconsciousness, severe breathing difficulty, massive trauma).\n\n"
        "Incident Description:\n"
        f"\"{input_data.consolidated_text}\"\n\n"
        "Respond with ONLY a JSON object in this exact format and nothing else:\n"
        '{"severity_score": <int 1-10>, "confidence": <0.0-1.0>, "reasoning": "<1-2 sentences explaining why>"}'
    )

    try:
        raw = await complete(
            prompt=prompt,
            model=SMALL_MODEL,
            temperature=0.0,
            max_tokens=300,
        )

        parsed = _parse_llm_response(raw)
        if parsed is None:
            raise ValueError(f"Could not parse LLM response: {raw!r}")

        score = parsed.get("severity_score")
        if not isinstance(score, int) or not (1 <= score <= 10):
            raise ValueError(f"Invalid severity score returned: {score}")

        llm_confidence = float(parsed.get("confidence", 0.5))
        llm_reasoning = str(parsed.get("reasoning", "LLM determined severity."))

        output = TriageOutput(severity_score=score)
        
        # Cap confidence slightly to reflect LLM uncertainty, but allow high confidence
        # if the model is very sure.
        confidence = min(llm_confidence, 0.95)
        source = "llm"
        reasoning = llm_reasoning

    except LLMGatewayError as exc:
        logger.warning(
            "TriageAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "TriageAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"Parse error: {exc}")

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "TriageAgent: %s | score=%d | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id,
        output.severity_score,
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

def _fallback_result(reason: str) -> tuple[TriageOutput, str, str, float]:
    """
    Fallback when Triage LLM fails.
    Defaults to severity 5 (moderate/urgent but not critical, safe middle ground).
    Sets confidence=0.3 so orchestrator flags requires_human_review=True.
    """
    output = TriageOutput(severity_score=5)
    reasoning = (
        f"Triage evaluation failed ({reason}). "
        "Defaulted to moderate severity score 5. "
        "Human review required."
    )
    return output, reasoning, "fallback", 0.3


def _parse_llm_response(raw: str) -> Optional[dict]:
    """
    Extract JSON object from LLM response.
    Handles potential markdown code fences.
    """
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
