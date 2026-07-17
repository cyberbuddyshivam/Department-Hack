"""
agents/intake.py
AEGIS — Intake Agent (Step 4 in build order)

Responsibility:
  Normalise every field of IncidentInput, consolidate all text sources into
  a single coherent description, and resolve the caller location to lat/lng
  coordinates so downstream agents never have to deal with raw free-text addresses.

Contract (from architecture.md §4):
  Input:  IncidentInput (passed in full — this is the only agent that touches it)
  Output: AgentResult[IntakeOutput]
  Fallback trigger: LLM call fails (LLMGatewayError) → extract_location_fallback()
                    returns IntakeOutput with source="fallback", confidence≤0.4

Key design decisions:
  1. The Intake Agent makes AT MOST ONE LLM call — only when lat/lng are absent
     and raw_text is present (geocoding via the small model).
     When lat/lng are already provided, no LLM call is made at all.
  2. Input sanitization happens here before any text enters a prompt.
     We call guardrails.sanitizer.sanitize() on every text field.
  3. The consolidated_text field is what all downstream agents receive instead
     of the full IncidentInput — it's a clean single string merging all sources.
  4. No agent downstream touches IncidentInput directly. This is the boundary.

Prompt design:
  The geocoding prompt asks the model for a JSON object with lat/lng.
  We use SMALL_MODEL (fast, low-latency) since geocoding is a simple lookup task.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

import asyncio
import httpx
from guardrails.sanitizer import sanitize
from llm_gateway import complete, LLMGatewayError, SMALL_MODEL
from models.agent_result import AgentResult
from models.input import IncidentInput

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"


# ---------------------------------------------------------------------------
# Intake agent output schema
# ---------------------------------------------------------------------------

class ResolvedLocation(BaseModel):
    """Lat/lng pair after geocoding. raw_text preserved for the trace."""

    lat: Optional[float] = Field(default=None, description="WGS-84 latitude.")
    lng: Optional[float] = Field(default=None, description="WGS-84 longitude.")
    raw_text: Optional[str] = Field(
        default=None,
        description="Original free-text location as supplied by the caller.",
    )
    geocoded: bool = Field(
        default=False,
        description=(
            "True when lat/lng were derived from raw_text via the LLM geocoder. "
            "False when lat/lng came directly from the caller (GPS)."
        ),
    )


class IntakeOutput(BaseModel):
    """
    Normalised incident data produced by the Intake Agent.

    This is the only agent-output object that contains the full incident text.
    All downstream agents receive a subset of this, never the raw IncidentInput.
    """

    incident_id: str = Field(description="Propagated from IncidentInput unchanged.")
    consolidated_text: str = Field(
        description=(
            "All available text sources merged into one clean paragraph. "
            "Used as the primary text input for Triage, Verifier, and Classifier."
        )
    )
    location: ResolvedLocation = Field(
        description="Caller location, with lat/lng resolved where possible."
    )
    caller_name: Optional[str] = Field(
        default=None, description="Caller name from CallerMeta."
    )
    caller_phone: Optional[str] = Field(
        default=None, description="Caller phone from CallerMeta."
    )
    caller_relation: Optional[str] = Field(
        default=None, description="Caller relation to patient from CallerMeta."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(incident: IncidentInput) -> AgentResult[IntakeOutput]:
    """
    Normalise IncidentInput and resolve location.

    This function is the sole public API of the Intake Agent.
    The orchestrator calls it as:
        intake_result = await intake.run(incident)

    Parameters
    ----------
    incident : IncidentInput
        The raw incident as received from POST /incident.

    Returns
    -------
    AgentResult[IntakeOutput]
        Always returns a result — never raises. On LLM failure, returns a
        fallback result with source="fallback" and confidence≤0.4.
    """
    t_start = time.monotonic()

    # Step 1: Sanitize all text fields
    clean_text = _sanitize_sources(incident)
    clean_location_text = (
        sanitize(incident.caller_location.raw_text)
        if incident.caller_location.raw_text
        else None
    )

    # Step 2: Consolidate all text sources into one paragraph
    consolidated = _consolidate_text(clean_text)

    # Step 3: Resolve location
    if _has_gps(incident):
        # GPS present — no LLM call needed
        location = ResolvedLocation(
            lat=incident.caller_location.lat,
            lng=incident.caller_location.lng,
            raw_text=incident.caller_location.raw_text,
            geocoded=False,
        )
        reasoning = (
            "GPS coordinates supplied directly by caller device. "
            f"Location: ({location.lat:.4f}, {location.lng:.4f}). "
            f"Text sources consolidated from: {_source_names(incident)}."
        )
        source = "llm"     # no LLM needed, but result is fully resolved
        confidence = 0.95

    elif clean_location_text:
        # No GPS — attempt Nominatim geocoding
        location, reasoning, source, confidence = await _geocode_via_nominatim(
            clean_location_text, incident.incident_id
        )
        reasoning = (
            f"Text sources consolidated from: {_source_names(incident)}. "
            + reasoning
        )
    else:
        # No GPS and no location text — minimal fallback
        location = ResolvedLocation(geocoded=False)
        reasoning = (
            "No location data supplied (no GPS, no raw_text). "
            "Downstream agents will flag for human review."
        )
        source = "fallback"
        confidence = 0.3

    latency_ms = (time.monotonic() - t_start) * 1000

    output = IntakeOutput(
        incident_id=incident.incident_id,
        consolidated_text=consolidated,
        location=location,
        caller_name=incident.caller_meta.name,
        caller_phone=incident.caller_meta.phone,
        caller_relation=incident.caller_meta.relation,
    )

    logger.info(
        "IntakeAgent: %s | src=%s | conf=%.2f | %.0f ms",
        incident.incident_id,
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

def _sanitize_sources(incident: IncidentInput) -> dict[str, Optional[str]]:
    """Return a dict of sanitized text fields from input_sources."""
    srcs = incident.input_sources
    return {
        "text": sanitize(srcs.text) if srcs.text else None,
        "audio_transcript": sanitize(srcs.audio_transcript) if srcs.audio_transcript else None,
        "call_transcript": sanitize(srcs.call_transcript) if srcs.call_transcript else None,
    }


def _consolidate_text(clean: dict[str, Optional[str]]) -> str:
    """
    Merge all available text sources into one clean paragraph.

    Priority order (most to least authoritative):
    1. call_transcript  (real-time, most context)
    2. text             (dispatcher note, direct)
    3. audio_transcript (post-processed audio)

    Each present source is prefixed with its label so downstream agents
    can see provenance without being confused by duplicate information.
    """
    parts = []
    if clean.get("call_transcript"):
        parts.append(f"[Call Transcript] {clean['call_transcript']}")
    if clean.get("text"):
        parts.append(f"[Dispatcher Note] {clean['text']}")
    if clean.get("audio_transcript"):
        parts.append(f"[Audio Transcript] {clean['audio_transcript']}")

    if not parts:
        return "(no text description provided)"
    return "\n\n".join(parts)


def _source_names(incident: IncidentInput) -> str:
    """Return a human-readable list of which sources are populated."""
    srcs = incident.input_sources
    present = []
    if srcs.call_transcript:
        present.append("call_transcript")
    if srcs.text:
        present.append("text")
    if srcs.audio_transcript:
        present.append("audio_transcript")
    if srcs.image_refs:
        present.append(f"image_refs({len(srcs.image_refs)})")
    return ", ".join(present) if present else "none"


def _has_gps(incident: IncidentInput) -> bool:
    """True when both lat and lng are present."""
    loc = incident.caller_location
    return loc.lat is not None and loc.lng is not None


async def _geocode_via_nominatim(
    location_text: str,
    incident_id: str,
) -> tuple[ResolvedLocation, str, str, float]:
    """
    Use Nominatim to extract approximate lat/lng from a free-text location.
    Appends ', Maharashtra, India' if not present.
    """
    search_text = location_text.strip()
    if "Maharashtra" not in search_text and "India" not in search_text:
        search_text += ", Maharashtra, India"

    try:
        # Respect Nominatim's 1 req/sec policy
        await asyncio.sleep(1.0)
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": search_text, "format": "json", "limit": 1},
                headers={"User-Agent": "AEGIS-Intake/1.0"},
                timeout=10.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data and len(data) > 0:
                lat = float(data[0]["lat"])
                lng = float(data[0]["lon"])
                
                location = ResolvedLocation(
                    lat=lat,
                    lng=lng,
                    raw_text=location_text,
                    geocoded=True,
                )
                reasoning = f"Nominatim geocoded '{search_text}' -> ({lat:.4f}, {lng:.4f})."
                return location, reasoning, "llm", 0.95
            else:
                return _geocode_fallback(location_text, f"Nominatim found no results for '{search_text}'.")
                
    except Exception as exc:
        logger.warning(
            "IntakeAgent[%s]: Nominatim geocoding failed — %s. Using fallback.",
            incident_id,
            exc,
        )
        return _geocode_fallback(location_text, f"Nominatim unavailable: {exc}")


def _geocode_fallback(
    location_text: str,
    reason: str,
) -> tuple[ResolvedLocation, str, str, float]:
    """
    Fallback when LLM geocoding fails.
    Preserves raw_text so human reviewers still see the location description.
    Sets confidence=0.3 so the orchestrator flags requires_human_review=True.
    """
    location = ResolvedLocation(
        lat=None,
        lng=None,
        raw_text=location_text,
        geocoded=False,
    )
    reasoning = (
        f"Location geocoding failed ({reason}). "
        f"Raw location text preserved: '{location_text}'. "
        "Human review required to confirm coordinates."
    )
    return location, reasoning, "fallback", 0.3


def _parse_geocode_response(raw: str) -> Optional[dict]:
    """
    Extract the JSON object from the LLM's response.
    Handles cases where the model wraps JSON in markdown code fences.
    """
    # Strip markdown code fences if present
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Find the first complete JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    json_str = text[brace_start: brace_end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None
