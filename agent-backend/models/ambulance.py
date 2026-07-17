"""
models/ambulance.py
Ambulance mock-data record — mirrors the schema a real CAD (Computer-Aided
Dispatch) system would expose.

Equipment taxonomy (resolves the open question in progress-tracker.md):
  BLS equipment (all BLS units carry these):
    "stretcher", "oxygen", "aed", "basic_first_aid", "splints", "pulse_oximeter"
  ALS equipment (superset of BLS, plus):
    "cardiac_monitor", "iv_access", "epinephrine", "intubation_kit",
    "12_lead_ecg", "ventilator"
  Trauma equipment (superset of ALS, plus):
    "blood_products", "thoracic_decompression_kit", "tourniquet_set",
    "trauma_dressings"
  Neonatal equipment:
    "neonatal_incubator", "neonatal_ventilator", "neonatal_monitor",
    "umbilical_catheter_kit", "neonatal_iv_access", "surfactant"
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AmbulanceType = Literal["BLS", "ALS", "trauma", "neonatal"]
AmbulanceStatus = Literal["available", "dispatched", "maintenance"]

AmbulanceEquipment = Literal[
    # BLS
    "stretcher",
    "oxygen",
    "aed",
    "basic_first_aid",
    "splints",
    "pulse_oximeter",
    # ALS
    "cardiac_monitor",
    "iv_access",
    "epinephrine",
    "intubation_kit",
    "12_lead_ecg",
    "ventilator",
    # Trauma (ALS superset)
    "blood_products",
    "thoracic_decompression_kit",
    "tourniquet_set",
    "trauma_dressings",
    # Neonatal
    "neonatal_incubator",
    "neonatal_ventilator",
    "neonatal_monitor",
    "umbilical_catheter_kit",
    "neonatal_iv_access",
    "surfactant",
]


class Ambulance(BaseModel):
    """A single ambulance record as stored in ambulances.json."""

    id: str = Field(description="Unique ambulance identifier, e.g. 'amb_001'.")
    type: AmbulanceType = Field(
        description="Service level: BLS (basic), ALS (advanced), trauma, or neonatal."
    )
    lat: float = Field(ge=-90.0, le=90.0, description="Current WGS-84 latitude.")
    lng: float = Field(ge=-180.0, le=180.0, description="Current WGS-84 longitude.")
    status: AmbulanceStatus = Field(
        description=(
            "Operational status. Mutable in-memory: Dispatch Agent flips "
            "'available' → 'dispatched' on assignment."
        )
    )
    equipment: list[AmbulanceEquipment] = Field(
        min_length=1,
        description="Equipment carried by this unit.",
    )
