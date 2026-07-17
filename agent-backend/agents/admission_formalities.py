"""
agents/admission_formalities.py
AEGIS — Admission Formalities Agent (Step 9 in build order)

Responsibility:
  Generates a pre-filled admission report and a human-readable brief summarizing
  the entire incident and decision. Uses the LARGE_MODEL for complex summarization.

Contract:
  Input:  FormalitiesInput (all resolved data from previous stages)
  Output: AgentResult[FormalitiesOutput]
  Fallback: Rule-based generation of a minimal admission report and brief,
            source="fallback", confidence≤0.4.

Prompt design:
  LARGE_MODEL receives the full incident context and decisions.
  Returns JSON matching the HospitalAdmissionReport structure + human_readable_brief.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from llm_gateway import complete, LLMGatewayError, LARGE_MODEL
from models.agent_result import AgentResult
from models.output import AssignedAmbulance, AssignedHospital, HospitalAdmissionReport

logger = logging.getLogger(__name__)

AGENT_NAME = "admission_formalities"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FormalitiesInput(BaseModel):
    """Input subset required by the Admission Formalities Agent."""
    incident_id: str
    consolidated_text: str
    patient_name: Optional[str]
    caller_phone: Optional[str]
    severity_score: int
    ambulance: AssignedAmbulance
    hospital: AssignedHospital


class FormalitiesOutput(BaseModel):
    """Agent-specific typed output for Admission Formalities."""
    report: HospitalAdmissionReport
    human_readable_brief: str


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(input_data: FormalitiesInput) -> AgentResult[FormalitiesOutput]:
    t_start = time.monotonic()
    
    prompt = (
        "You are an expert medical scribe and emergency dispatcher. Your task is to generate "
        "a hospital admission report and a short human-readable brief based on the provided emergency incident.\n\n"
        f"Incident Description: \"{input_data.consolidated_text}\"\n"
        f"Patient Name: {input_data.patient_name or 'Unknown'}\n"
        f"Caller Phone: {input_data.caller_phone or 'Unknown'}\n"
        f"Severity Score: {input_data.severity_score}/10\n"
        f"Dispatched Ambulance: {input_data.ambulance.type} (ID: {input_data.ambulance.ambulance_id}, ETA: {input_data.ambulance.eta_minutes} mins)\n"
        f"Assigned Hospital: {input_data.hospital.name} (Distance: {input_data.hospital.distance_km} km)\n\n"
        "Respond with ONLY a JSON object in this exact format and nothing else:\n"
        "{\n"
        '  "incident_summary": "<One-sentence structured summary>",\n'
        '  "presenting_complaint": "<Clinical description of primary complaint>",\n'
        '  "suspected_diagnosis": "<Preliminary diagnosis, or null>",\n'
        '  "special_preparations": ["<Prep 1>", "<Prep 2>"],\n'
        '  "human_readable_brief": "<Short paragraph (3-5 sentences) summarizing the incident, decision, and caveats>",\n'
        '  "confidence": <0.0-1.0>,\n'
        '  "reasoning": "<1 sentence explaining confidence>"\n'
        "}"
    )

    try:
        raw = await complete(
            prompt=prompt,
            model=LARGE_MODEL,
            temperature=0.0,
            max_tokens=500,
        )

        parsed = _parse_llm_response(raw)
        if parsed is None:
            raise ValueError(f"Could not parse LLM response: {raw!r}")

        summary = parsed.get("incident_summary")
        complaint = parsed.get("presenting_complaint")
        if not summary or not complaint:
            raise ValueError("Missing required fields (summary or complaint)")

        preps = parsed.get("special_preparations", [])
        if not isinstance(preps, list):
            preps = []

        brief = parsed.get("human_readable_brief")
        if not brief:
            raise ValueError("Missing human_readable_brief")

        report = HospitalAdmissionReport(
            patient_name=input_data.patient_name,
            caller_phone=input_data.caller_phone,
            incident_summary=summary,
            presenting_complaint=complaint,
            suspected_diagnosis=parsed.get("suspected_diagnosis"),
            severity_score=input_data.severity_score,
            ambulance_type=input_data.ambulance.type,
            estimated_arrival_minutes=input_data.ambulance.eta_minutes,
            special_preparations=preps,
            report_generated_at=datetime.now(timezone.utc)
        )

        llm_confidence = float(parsed.get("confidence", 0.5))
        llm_reasoning = str(parsed.get("reasoning", "LLM generated admission formalities."))

        output = FormalitiesOutput(
            report=report,
            human_readable_brief=brief
        )
        
        confidence = min(llm_confidence, 0.95)
        source = "llm"
        reasoning = llm_reasoning

    except LLMGatewayError as exc:
        logger.warning(
            "FormalitiesAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id, exc
        )
        output, reasoning, source, confidence = _fallback_result(input_data, f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "FormalitiesAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id, exc
        )
        output, reasoning, source, confidence = _fallback_result(input_data, f"Parse error: {exc}")

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "FormalitiesAgent: %s | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id, source, confidence, latency_ms
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

def _fallback_result(input_data: FormalitiesInput, reason: str) -> tuple[FormalitiesOutput, str, str, float]:
    """Fallback when Formalities LLM fails."""
    report = HospitalAdmissionReport(
        patient_name=input_data.patient_name,
        caller_phone=input_data.caller_phone,
        incident_summary="Emergency incident (LLM processing failed).",
        presenting_complaint=input_data.consolidated_text[:100] + "...",
        suspected_diagnosis=None,
        severity_score=input_data.severity_score,
        ambulance_type=input_data.ambulance.type,
        estimated_arrival_minutes=input_data.ambulance.eta_minutes,
        special_preparations=[],
        report_generated_at=datetime.now(timezone.utc)
    )
    
    brief = (
        f"Automated fallback brief due to LLM failure: Patient requires {input_data.ambulance.type} ambulance. "
        f"Assigned to {input_data.hospital.name}. Severity score {input_data.severity_score}. "
        "Review full incident text for details."
    )
    
    output = FormalitiesOutput(report=report, human_readable_brief=brief)
    reasoning = f"Formalities LLM evaluation failed ({reason}). Rule-based fallback generated minimal report."
    
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
