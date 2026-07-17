"""
data/mock_store.py
In-memory mutable state store — loaded once at process startup.

Responsibilities:
1. Parse hospitals.json and ambulances.json into validated Pydantic models.
2. Hold the canonical mutable copies in-memory (available_beds decrements,
   ambulance status flips) for the duration of the process.
3. Provide the idempotency/dedup store keyed by incident_id so that a retried
   POST /incident never double-assigns a resource.

Architecture invariants enforced here:
- Mock data mutation is in-memory only (no DB writes, no file writes).
- Dedup store is a plain dict; this is intentional for Phase 1.
  Replace with Redis only when multi-process horizontal scale is required.
- All public functions are synchronous (no I/O after startup) so agents can
  call them inside async functions without blocking the event loop.

Thread-safety note:
  FastAPI runs a single-process async event loop under uvicorn by default.
  Because asyncio is cooperative (not truly parallel), no two coroutines
  mutate the store simultaneously — no locks needed for Phase 1.
  If multiple workers are added later, replace this with Redis.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from models.hospital import Hospital
from models.ambulance import Ambulance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent
_HOSPITALS_PATH = _DATA_DIR / "hospitals.json"
_AMBULANCES_PATH = _DATA_DIR / "ambulances.json"


# ---------------------------------------------------------------------------
# In-memory stores (populated at import time — fail fast if JSON is corrupt)
# ---------------------------------------------------------------------------

def _load_hospitals() -> dict[str, Hospital]:
    """Parse hospitals.json into a dict keyed by hospital id."""
    raw: list[dict] = json.loads(_HOSPITALS_PATH.read_text(encoding="utf-8"))
    hospitals: dict[str, Hospital] = {}
    for record in raw:
        hospital = Hospital.model_validate(record)
        hospitals[hospital.id] = hospital
    logger.info("MockStore: loaded %d hospital records.", len(hospitals))
    return hospitals


def _load_ambulances() -> dict[str, Ambulance]:
    """Parse ambulances.json into a dict keyed by ambulance id."""
    raw: list[dict] = json.loads(_AMBULANCES_PATH.read_text(encoding="utf-8"))
    ambulances: dict[str, Ambulance] = {}
    for record in raw:
        ambulance = Ambulance.model_validate(record)
        ambulances[ambulance.id] = ambulance
    logger.info("MockStore: loaded %d ambulance records.", len(ambulances))
    return ambulances


# Mutable in-memory state — agents read/write these directly via the public API below.
_hospitals: dict[str, Hospital] = _load_hospitals()
_ambulances: dict[str, Ambulance] = _load_ambulances()

# Idempotency / dedup store: incident_id → {"ambulance_id": str, "hospital_id": str}
# Written on first successful assignment; checked before every subsequent assignment.
_dedup_store: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def get_all_hospitals() -> list[Hospital]:
    """Return all hospital records (current in-memory state)."""
    return list(_hospitals.values())


def get_hospital(hospital_id: str) -> Optional[Hospital]:
    """Return a single hospital by ID, or None if not found."""
    return _hospitals.get(hospital_id)


def get_all_ambulances() -> list[Ambulance]:
    """Return all ambulance records (current in-memory state)."""
    return list(_ambulances.values())


def get_ambulance(ambulance_id: str) -> Optional[Ambulance]:
    """Return a single ambulance by ID, or None if not found."""
    return _ambulances.get(ambulance_id)


def get_available_ambulances() -> list[Ambulance]:
    """Return all ambulances whose status is 'available'."""
    return [a for a in _ambulances.values() if a.status == "available"]


def get_hospitals_with_available_beds() -> list[Hospital]:
    """Return all hospitals with at least one available bed across any category."""
    return [
        h for h in _hospitals.values() 
        if (h.beds.icu.available > 0 or 
            h.beds.emergency.available > 0 or 
            h.beds.general.available > 0 or 
            h.beds.pediatric.available > 0)
    ]


# ---------------------------------------------------------------------------
# Public write API (idempotency-safe — check dedup store before mutating)
# ---------------------------------------------------------------------------

def assign_ambulance(incident_id: str, ambulance_id: str) -> bool:
    """
    Mark an ambulance as dispatched for an incident.

    Returns True on first successful assignment.
    Returns False (no-op) if this incident_id already has an assignment
    recorded in the dedup store (idempotent retry safety).

    Raises ValueError if the ambulance_id does not exist or is not available.
    """
    existing = _dedup_store.get(incident_id, {})
    if "ambulance_id" in existing:
        logger.info(
            "MockStore.assign_ambulance: incident %s already assigned ambulance %s — no-op.",
            incident_id,
            existing["ambulance_id"],
        )
        return False

    ambulance = _ambulances.get(ambulance_id)
    if ambulance is None:
        raise ValueError(f"Ambulance '{ambulance_id}' not found in mock store.")
    if ambulance.status != "available":
        raise ValueError(
            f"Ambulance '{ambulance_id}' is not available (status='{ambulance.status}')."
        )

    ambulance.status = "dispatched"
    _dedup_store.setdefault(incident_id, {})["ambulance_id"] = ambulance_id
    logger.info(
        "MockStore: ambulance %s dispatched for incident %s.", ambulance_id, incident_id
    )
    return True


def assign_hospital_bed(incident_id: str, hospital_id: str, bed_type: str = "general") -> bool:
    """
    Decrement available beds by 1 for the given hospital and bed_type.

    Returns True on first successful assignment.
    Returns False (no-op) if this incident_id already has a hospital assignment.

    Raises ValueError if hospital_id does not exist, bed_type is invalid, or no available beds.
    """
    existing = _dedup_store.get(incident_id, {})
    if "hospital_id" in existing:
        logger.info(
            "MockStore.assign_hospital_bed: incident %s already assigned to hospital %s — no-op.",
            incident_id,
            existing["hospital_id"],
        )
        return False

    hospital = _hospitals.get(hospital_id)
    if hospital is None:
        raise ValueError(f"Hospital '{hospital_id}' not found in mock store.")
        
    # Get the specific bed category
    if not hasattr(hospital.beds, bed_type):
        raise ValueError(f"Invalid bed_type '{bed_type}' for hospital.")
        
    bed_category = getattr(hospital.beds, bed_type)
    if bed_category.available <= 0:
        raise ValueError(
            f"Hospital '{hospital_id}' has no available beds of type '{bed_type}'."
        )

    bed_category.available -= 1
    _dedup_store.setdefault(incident_id, {})["hospital_id"] = hospital_id
    logger.info(
        "MockStore: %s bed assigned at hospital %s for incident %s (remaining beds: %d).",
        bed_type,
        hospital_id,
        incident_id,
        bed_category.available,
    )
    return True


# ---------------------------------------------------------------------------
# Dedup store read API (for orchestrator to check prior assignments)
# ---------------------------------------------------------------------------

def get_assignment(incident_id: str) -> dict[str, str]:
    """
    Return the assignment dict for an incident_id.
    Keys present: 'ambulance_id' and/or 'hospital_id' if already assigned.
    Returns empty dict if incident has no prior assignment.
    """
    return _dedup_store.get(incident_id, {})


def is_duplicate_incident(incident_id: str) -> bool:
    """
    Return True if this incident_id has already been processed (any assignment exists).
    Lets the orchestrator short-circuit a fully retried incident at the top level.
    """
    return incident_id in _dedup_store
