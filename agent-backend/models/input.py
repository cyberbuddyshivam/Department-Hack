"""
models/input.py
IncidentInput and all sub-models that arrive at POST /incident.

Design rules:
- Every field is typed; no raw dicts cross agent boundaries.
- `input_sources` allows any combination of text / audio_transcript / image_refs /
  call_transcript — all are Optional so callers can omit fields they don't have.
- `caller_location` holds either structured lat/lng OR a raw free-text address;
  the Intake Agent geocodes raw_text into lat/lng when needed.
- All fields use snake_case; Pydantic v2 serialises by alias if needed downstream.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InputSources(BaseModel):
    """Multimodal inputs supplied by the dispatcher / caller intake system."""

    text: Optional[str] = Field(
        default=None,
        description="Free-text description of the emergency typed by the dispatcher.",
    )
    audio_transcript: Optional[str] = Field(
        default=None,
        description="Transcript generated from an audio recording of the incident call.",
    )
    image_refs: list[str] = Field(
        default_factory=list,
        description=(
            "List of image reference IDs or URLs (e.g. crash-scene photos). "
            "These are treated as data references, not embedded blobs."
        ),
    )
    call_transcript: Optional[str] = Field(
        default=None,
        description="Verbatim transcript of the live emergency call.",
    )

    @field_validator("text", "audio_transcript", "call_transcript", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Normalise leading/trailing whitespace before any agent sees the text."""
        return v.strip() if isinstance(v, str) else v


class CallerLocation(BaseModel):
    """Location of the incident, supplied as structured coordinates and/or raw text."""

    lat: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="WGS-84 latitude. Present when the caller device supplies GPS.",
    )
    lng: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="WGS-84 longitude. Present when the caller device supplies GPS.",
    )
    raw_text: Optional[str] = Field(
        default=None,
        description=(
            "Free-text location description (e.g. 'near the Starbucks on 5th Ave'). "
            "The Intake Agent geocodes this when lat/lng are absent."
        ),
    )


class CallerMeta(BaseModel):
    """Identifying information about the person reporting the emergency."""

    name: Optional[str] = Field(
        default=None,
        description="Name of the person calling in the incident.",
    )
    phone: Optional[str] = Field(
        default=None,
        description="Callback phone number for the caller.",
    )
    relation: Optional[str] = Field(
        default=None,
        description=(
            "Caller's relation to the patient — e.g. 'patient', 'bystander', "
            "'family member', 'first responder'."
        ),
    )


class IncidentInput(BaseModel):
    """
    Root input schema for POST /incident.

    A new incident_id is auto-generated if not supplied by the caller
    (callers may supply one for idempotent retries).
    """

    incident_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this incident. Used for idempotency.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the incident was reported. Defaults to ingestion time (UTC).",
    )
    input_sources: InputSources = Field(
        description="One or more multimodal inputs describing the emergency.",
    )
    caller_location: CallerLocation = Field(
        description="Where the emergency is occurring.",
    )
    caller_meta: CallerMeta = Field(
        default_factory=CallerMeta,
        description="Metadata about the person reporting the incident.",
    )
