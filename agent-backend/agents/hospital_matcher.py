"""
agents/hospital_matcher.py
AEGIS — Hospital Matcher Agent (Step 8 in build order, runs parallel to Dispatch)

Responsibility:
  Select the most appropriate hospital for the incident. The Python code handles
  deterministic filtering (available beds, trauma center requirements, distance),
  and the LLM selects the final candidate and writes the reasoning.

Contract:
  Input:  MatcherInput (incident_id, caller_location, incident text, severity, ambulance type)
  Output: AgentResult[MatcherOutput]
  Idempotency: Must call mock_store.assign_hospital_bed to mutate state safely.
  Fallback: Rule-based assignment of the closest matching hospital without LLM,
            source="fallback", confidence≤0.4.

Prompt design:
  SMALL_MODEL receives the top 3 closest matching hospitals and the incident context.
  Returns JSON selecting the best one and explaining why.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from data import mock_store
from llm_gateway import complete, LLMGatewayError, SMALL_MODEL
from models.agent_result import AgentResult
from models.ambulance import AmbulanceType
from agents.intake import ResolvedLocation
from models.output import AssignedHospital

logger = logging.getLogger(__name__)

AGENT_NAME = "hospital_matcher"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MatcherInput(BaseModel):
    """Input subset required by the Hospital Matcher."""
    incident_id: str
    caller_location: ResolvedLocation
    consolidated_text: str
    severity_score: int
    ambulance_type: AmbulanceType


class MatcherOutput(BaseModel):
    """Agent-specific typed output for Hospital Matcher."""
    assigned_hospital: AssignedHospital
    bed_mismatch: bool = Field(
        default=False,
        description="True if the assigned hospital did not have the required bed type available."
    )


# ---------------------------------------------------------------------------
# Distance Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(input_data: MatcherInput) -> AgentResult[MatcherOutput]:
    t_start = time.monotonic()
    
    # 1. Check idempotency: did we already assign a bed for this incident?
    existing_assignment = mock_store.get_assignment(input_data.incident_id)
    if "hospital_id" in existing_assignment:
        hosp_id = existing_assignment["hospital_id"]
        hosp = mock_store.get_hospital(hosp_id)
        if hosp:
            dist = None
            if input_data.caller_location.lat is not None and input_data.caller_location.lng is not None:
                dist = round(_haversine_km(
                    input_data.caller_location.lat, input_data.caller_location.lng,
                    hosp.lat, hosp.lng
                ), 1)
            
            output = MatcherOutput(
                assigned_hospital=AssignedHospital(
                    hospital_id=hosp.id,
                    name=hosp.name,
                    distance_km=dist
                )
            )
            logger.info("HospitalMatcher: Idempotent return for incident %s", input_data.incident_id)
            return AgentResult(
                agent_name=AGENT_NAME,
                result=output,
                reasoning="Idempotent return from previous successful hospital match.",
                confidence=1.0,
                source="llm",
                latency_ms=round((time.monotonic() - t_start) * 1000, 1),
            )

    # 2. Filter available hospitals
    candidates = mock_store.get_hospitals_with_available_beds()
    
    # Filter by required capability
    req_bed = "general"
    if input_data.ambulance_type == "trauma":
        req_bed = "icu"
        candidates = [h for h in candidates if h.has_trauma_center and h.beds.icu.available > 0]
    elif input_data.ambulance_type == "neonatal":
        req_bed = "pediatric"
        candidates = [
            h for h in candidates 
            if ("neonatal_icu" in h.specialties or "pediatrics" in h.specialties) and h.beds.pediatric.available > 0
        ]
    elif input_data.ambulance_type == "ALS":
        req_bed = "emergency"
        candidates = [h for h in candidates if h.beds.emergency.available > 0]
    else:
        candidates = [h for h in candidates if h.beds.general.available > 0]
        
    bed_mismatch = False
    if not candidates:
        logger.warning(
            "MatcherAgent[%s]: No hospitals with %s beds available. Falling back to any available bed.",
            input_data.incident_id, req_bed
        )
        candidates = mock_store.get_hospitals_with_available_beds()
        if not candidates:
            return _fallback_no_candidates(input_data, t_start)
        bed_mismatch = True
        
        # If we fallback, try to at least find a general bed
        fallback_req = "general"
        if not any(getattr(c.beds, fallback_req).available > 0 for c in candidates):
            # Just take whatever bed category has space
            for bt in ["emergency", "pediatric", "icu"]:
                if any(getattr(c.beds, bt).available > 0 for c in candidates):
                    fallback_req = bt
                    break
        req_bed = fallback_req
        # Filter candidates to those that actually have the fallback bed
        candidates = [c for c in candidates if getattr(c.beds, req_bed).available > 0]
        
    if not candidates:
        return _fallback_no_candidates(input_data, t_start)
    
    # 3. Sort by distance (if caller location has lat/lng)
    caller_lat = input_data.caller_location.lat
    caller_lng = input_data.caller_location.lng
    
    if caller_lat is not None and caller_lng is not None:
        def dist_fn(hosp):
            return _haversine_km(caller_lat, caller_lng, hosp.lat, hosp.lng)
        candidates.sort(key=dist_fn)
    
    selected_hosp = candidates[0]
    
    dist_str = "Unknown"
    if caller_lat is not None and caller_lng is not None:
        d = _haversine_km(caller_lat, caller_lng, selected_hosp.lat, selected_hosp.lng)
        dist_str = f"{d:.1f} km"

    if bed_mismatch:
        mismatch_warning = (
            f"\nWARNING: The incident required a '{req_bed}' bed (based on ambulance/severity), "
            f"but none were available nearby. You were FORCED to assign a '{req_bed}' bed at {selected_hosp.name}. "
            f"You MUST explicitly state this mismatch in your reasoning."
        )
    else:
        mismatch_warning = ""

    prompt = (
        "You are an expert emergency medical dispatcher. We have deterministically assigned the following hospital based on shortest distance and required capabilities:\n"
        f"Assigned Hospital: {selected_hosp.name} (ID: {selected_hosp.id}, Distance: {dist_str}, "
        f"Beds Available [ICU: {selected_hosp.beds.icu.available}, ER: {selected_hosp.beds.emergency.available}, Gen: {selected_hosp.beds.general.available}], "
        f"Specialties: {', '.join(selected_hosp.specialties)})\n"
        f"{mismatch_warning}\n\n"
        f"Incident Description: \"{input_data.consolidated_text}\"\n"
        f"Severity Score: {input_data.severity_score}\n"
        f"Ambulance Type Dispatched: {input_data.ambulance_type}\n\n"
        "Write the reasoning for why this hospital assignment is correct. Respond with ONLY a JSON object in this exact format:\n"
        '{"confidence": <0.0-1.0>, "reasoning": "<1-2 sentences explaining why this hospital matches the incident>"}'
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

        llm_confidence = float(parsed.get("confidence", 0.95))
        llm_reasoning = str(parsed.get("reasoning", "LLM validated deterministic selection."))
        
        if bed_mismatch:
            confidence = min(llm_confidence, 0.4)
            reasoning = f"[BED MISMATCH] {llm_reasoning}"
        else:
            confidence = min(llm_confidence, 0.95)
            reasoning = llm_reasoning
            
        source = "llm"

    except LLMGatewayError as exc:
        logger.warning(
            "MatcherAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id, exc
        )
        selected_hosp, reasoning, source, confidence = _fallback_result(selected_hosp, f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "MatcherAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id, exc
        )
        selected_hosp, reasoning, source, confidence = _fallback_result(selected_hosp, f"Parse error: {exc}")

    # Calculate final distance
    dist = None
    if caller_lat is not None and caller_lng is not None:
        d = _haversine_km(caller_lat, caller_lng, selected_hosp.lat, selected_hosp.lng)
        dist = round(d, 1)

    output = MatcherOutput(
        assigned_hospital=AssignedHospital(
            hospital_id=selected_hosp.id,
            name=selected_hosp.name,
            distance_km=dist
        ),
        bed_mismatch=bed_mismatch
    )

    # State mutation: assign the bed in the mock store
    try:
        mock_store.assign_hospital_bed(input_data.incident_id, selected_hosp.id, req_bed)
    except ValueError as e:
        logger.error("Failed to assign bed at %s: %s", selected_hosp.id, e)

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "MatcherAgent: %s | assigned=%s | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id, selected_hosp.id, source, confidence, latency_ms
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

def _fallback_result(best_candidate, reason: str) -> tuple[any, str, str, float]:
    reasoning = (
        f"Matcher LLM evaluation failed ({reason}). "
        f"Rule-based fallback selected closest matching hospital {best_candidate.id}."
    )
    return best_candidate, reasoning, "fallback", 0.3


def _fallback_no_candidates(input_data: MatcherInput, t_start: float) -> AgentResult[MatcherOutput]:
    """When absolutely no hospital matches the requirements."""
    all_av = mock_store.get_all_hospitals()
    if not all_av:
        raise RuntimeError("CRITICAL: No hospitals exist in the system.")
    
    # Just take the first available even if beds=0 (emergency override)
    selected = all_av[0]
    reasoning = (
        f"No hospitals available matching requirements (type {input_data.ambulance_type}, beds > 0). "
        f"Emergency fallback selected {selected.id} as a last resort. "
        "Human review URGENTLY required."
    )
    output = MatcherOutput(
        assigned_hospital=AssignedHospital(
            hospital_id=selected.id,
            name=selected.name,
            distance_km=None
        ),
        bed_mismatch=True
    )
    
    # We attempt to assign, but it will log an error if beds=0
    try:
        mock_store.assign_hospital_bed(input_data.incident_id, selected.id, "general")
    except ValueError:
        pass

    latency_ms = (time.monotonic() - t_start) * 1000
    return AgentResult(
        agent_name=AGENT_NAME,
        result=output,
        reasoning=reasoning,
        confidence=0.1,
        source="fallback",
        latency_ms=round(latency_ms, 1)
    )


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
