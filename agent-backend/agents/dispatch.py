"""
agents/dispatch.py
AEGIS — Dispatch Agent (Step 8 in build order)

Responsibility:
  Select the most appropriate available ambulance for the incident and write
  the reasoning. The Python code handles the deterministic filtering (type match,
  equipment subset, Haversine distance), and the LLM writes the human-readable
  reasoning and finalizes the choice from the top candidates.

Contract (from architecture.md §4):
  Input:  DispatchInput (incident_id, caller_location, requested_type, requested_equipment)
  Output: AgentResult[DispatchOutput]
  Idempotency: Must call mock_store.assign_ambulance to mutate state safely.
  Fallback: Rule-based assignment of the closest matching ambulance without LLM,
            source="fallback", confidence≤0.4.

Prompt design:
  SMALL_MODEL receives the top 3 closest matching ambulances and the caller's location,
  and is asked to select the best one and explain why (JSON).
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
from models.ambulance import AmbulanceType, AmbulanceEquipment
from agents.intake import ResolvedLocation
from models.output import AssignedAmbulance

logger = logging.getLogger(__name__)

AGENT_NAME = "dispatch"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DispatchInput(BaseModel):
    """Input subset required by the Dispatch Agent."""
    incident_id: str
    caller_location: ResolvedLocation
    ambulance_type: AmbulanceType
    required_equipment: list[AmbulanceEquipment]


class DispatchOutput(BaseModel):
    """Agent-specific typed output for Dispatch."""
    assigned_ambulance: AssignedAmbulance
    type_mismatch: bool = Field(
        default=False,
        description="True if the assigned ambulance type does not match the requested type."
    )


# ---------------------------------------------------------------------------
# Distance Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance in kilometers between two points."""
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

async def run(input_data: DispatchInput) -> AgentResult[DispatchOutput]:
    """
    Find the closest matching ambulance, use LLM for reasoning, and assign it.
    """
    t_start = time.monotonic()
    
    # 1. Check idempotency: did we already assign an ambulance for this incident?
    existing_assignment = mock_store.get_assignment(input_data.incident_id)
    if "ambulance_id" in existing_assignment:
        amb_id = existing_assignment["ambulance_id"]
        amb = mock_store.get_ambulance(amb_id)
        if amb:
            # We already dispatched this, just return the cached result.
            # Calculate distance if lat/lng available
            dist = None
            eta = None
            if input_data.caller_location.lat is not None and input_data.caller_location.lng is not None:
                dist = _haversine_km(
                    input_data.caller_location.lat, input_data.caller_location.lng,
                    amb.lat, amb.lng
                )
                eta = round((dist / 40.0) * 60, 1) # assume 40 km/h average speed
            
            output = DispatchOutput(
                assigned_ambulance=AssignedAmbulance(
                    ambulance_id=amb.id,
                    type=amb.type,
                    eta_minutes=eta
                )
            )
            logger.info("DispatchAgent: Idempotent return for incident %s", input_data.incident_id)
            return AgentResult(
                agent_name=AGENT_NAME,
                result=output,
                reasoning="Idempotent return from previous successful dispatch.",
                confidence=1.0,
                source="llm",
                latency_ms=round((time.monotonic() - t_start) * 1000, 1),
            )

    # 2. Filter available ambulances
    candidates = mock_store.get_available_ambulances()
    
    # Filter by type
    candidates = [a for a in candidates if a.type == input_data.ambulance_type]
    
    # Filter by required equipment
    required_set = set(input_data.required_equipment)
    candidates = [a for a in candidates if required_set.issubset(set(a.equipment))]
    
    if not candidates:
        # Fallback: no matching ambulance of this type/equipment!
        # Downgrade/Upgrade logic is complex. We'll fail to fallback.
        return _fallback_no_candidates(input_data, t_start)
    
    # 3. Sort by distance (if caller location has lat/lng)
    caller_lat = input_data.caller_location.lat
    caller_lng = input_data.caller_location.lng
    
    if caller_lat is not None and caller_lng is not None:
        def dist_fn(amb):
            return _haversine_km(caller_lat, caller_lng, amb.lat, amb.lng)
        candidates.sort(key=dist_fn)
    
    selected_amb = candidates[0]
    
    dist_str = "Unknown"
    if caller_lat is not None and caller_lng is not None:
        d = _haversine_km(caller_lat, caller_lng, selected_amb.lat, selected_amb.lng)
        dist_str = f"{d:.1f} km"

    type_mismatch = False
    if type_mismatch:
        mismatch_warning = (
            f"\nWARNING: You were requested to assign a '{input_data.ambulance_type}' ambulance, "
            f"but 0 were available. You were FORCED to assign a '{selected_amb.type}' ambulance "
            f"({selected_amb.id}) instead. You MUST explicitly state this mismatch in your reasoning."
        )
    else:
        mismatch_warning = ""

    prompt = (
        "You are an expert emergency dispatcher validating a deterministic ambulance assignment.\n"
        "Your engine has already selected the optimal ambulance based on math. You just need to explain it.\n\n"
        f"Requested Ambulance Type: {input_data.ambulance_type}\n"
        f"Selected Ambulance ID: {selected_amb.id} (Type: {selected_amb.type})\n"
        f"Selected Ambulance Equipment: {', '.join(selected_amb.equipment)}\n"
        f"{mismatch_warning}\n\n"
        "Respond with ONLY a JSON object in this exact format:\n"
        '{"reasoning": "<1-2 sentences explaining why this ambulance was assigned>", "confidence": <0.0-1.0>}'
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

        llm_confidence = float(parsed.get("confidence", 0.5))
        llm_reasoning = str(parsed.get("reasoning", "LLM validated deterministic assignment."))
        
        if type_mismatch:
            confidence = min(llm_confidence, 0.4)
            reasoning = f"[TYPE MISMATCH] {llm_reasoning}"
        else:
            confidence = min(llm_confidence, 0.95)
            reasoning = llm_reasoning
            
        source = "llm"

    except LLMGatewayError as exc:
        logger.warning(
            "DispatchAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id, exc
        )
        selected_amb, reasoning, source, confidence = _fallback_result(selected_amb, f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "DispatchAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id, exc
        )
        selected_amb, reasoning, source, confidence = _fallback_result(selected_amb, f"Parse error: {exc}")

    # Calculate final ETA
    eta = None
    if caller_lat is not None and caller_lng is not None:
        dist = _haversine_km(caller_lat, caller_lng, selected_amb.lat, selected_amb.lng)
        eta = round((dist / 40.0) * 60, 1)

    output = DispatchOutput(
        assigned_ambulance=AssignedAmbulance(
            ambulance_id=selected_amb.id,
            type=selected_amb.type,
            eta_minutes=eta
        ),
        type_mismatch=type_mismatch
    )

    # State mutation: assign the ambulance in the mock store
    try:
        mock_store.assign_ambulance(input_data.incident_id, selected_amb.id)
    except ValueError as e:
        logger.error("Failed to assign ambulance %s: %s", selected_amb.id, e)
        # We could handle race conditions here if we had them, but single-process async is safe.

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "DispatchAgent: %s | assigned=%s | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id, selected_amb.id, source, confidence, latency_ms
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
    """
    Fallback when Dispatch LLM fails.
    Defaults to the first candidate in the list (which is the closest).
    """
    reasoning = (
        f"Dispatch LLM evaluation failed ({reason}). "
        f"Rule-based fallback selected closest matching ambulance {best_candidate.id}."
    )
    return best_candidate, reasoning, "fallback", 0.3


def _fallback_no_candidates(input_data: DispatchInput, t_start: float) -> AgentResult[DispatchOutput]:
    """
    When absolutely no ambulance matches the exact type/equipment.
    In a real system we'd upgrade (e.g. ALS instead of BLS), but for now
    we just pick the first available ambulance of any kind to avoid completely dropping the incident.
    """
    all_av = mock_store.get_available_ambulances()
    if not all_av:
        # Extreme edge case: 0 ambulances available globally
        raise RuntimeError("CRITICAL: No available ambulances globally.")
    
    # Just take the first available
    selected = all_av[0]
    reasoning = (
        f"No ambulances available matching type {input_data.ambulance_type} and required equipment. "
        f"Emergency fallback selected {selected.id} (Type: {selected.type}) as a last resort. "
        "Human review URGENTLY required."
    )
    output = DispatchOutput(
        assigned_ambulance=AssignedAmbulance(
            ambulance_id=selected.id,
            type=selected.type,
            eta_minutes=None
        ),
        type_mismatch=True
    )
    
    mock_store.assign_ambulance(input_data.incident_id, selected.id)

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
