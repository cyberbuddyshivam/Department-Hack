"""
models/hospital.py
Hospital mock-data record — mirrors the schema that a real hospital DB/API
would expose. All fields are required (no Optional) so mock_store.py can rely
on complete records without defensive checks.

Taxonomy note (resolves the open question in progress-tracker.md):
  specialties are drawn from a fixed set:
    "trauma_surgery", "cardiology", "neurology", "orthopedics",
    "pediatrics", "neonatal_icu", "burns", "toxicology",
    "obstetrics", "general_emergency"

This list is realistic for a mid-size city and covers every ambulance type
(BLS/ALS/trauma/neonatal) that the Classifier agent can output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HospitalSpecialty = Literal[
    "trauma_surgery",
    "cardiology",
    "neurology",
    "orthopedics",
    "pediatrics",
    "neonatal_icu",
    "burns",
    "toxicology",
    "obstetrics",
    "general_emergency",
]


class BedCount(BaseModel):
    total: int = Field(ge=0, description="Total licensed beds of this type.")
    available: int = Field(ge=0, description="Currently available beds of this type.")


class HospitalBeds(BaseModel):
    icu: BedCount
    emergency: BedCount
    general: BedCount
    pediatric: BedCount


class Hospital(BaseModel):
    """A single hospital record as stored in hospitals.json."""

    id: str = Field(description="Unique hospital identifier, e.g. 'hosp_001'.")
    name: str = Field(description="Full name of the hospital.")
    lat: float = Field(ge=-90.0, le=90.0, description="WGS-84 latitude.")
    lng: float = Field(ge=-180.0, le=180.0, description="WGS-84 longitude.")
    specialties: list[HospitalSpecialty] = Field(
        min_length=1,
        description="List of clinical specialties available at this hospital.",
    )
    beds: HospitalBeds = Field(description="Nested bed availability metrics.")
    has_icu: bool = Field(description="Whether the hospital has an ICU.")
    has_trauma_center: bool = Field(
        description="Whether the hospital is a designated trauma centre."
    )
    has_cath_lab: bool = Field(default=False, description="Whether the hospital has a catheterization lab.")
    has_blood_bank: bool = Field(default=False, description="Whether the hospital has an in-house blood bank.")
