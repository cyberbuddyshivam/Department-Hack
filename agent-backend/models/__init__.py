# models package — exports all Pydantic v2 schemas used across the system
from .input import IncidentInput, InputSources, CallerLocation, CallerMeta
from .agent_result import AgentResult
from .output import (
    FinalOutput,
    FinalDecision,
    HospitalAdmissionReport,
    AssignedAmbulance,
    AssignedHospital,
)
from .hospital import Hospital
from .ambulance import Ambulance, AmbulanceType, AmbulanceStatus

__all__ = [
    "IncidentInput",
    "InputSources",
    "CallerLocation",
    "CallerMeta",
    "AgentResult",
    "FinalOutput",
    "FinalDecision",
    "HospitalAdmissionReport",
    "AssignedAmbulance",
    "AssignedHospital",
    "Hospital",
    "Ambulance",
    "AmbulanceType",
    "AmbulanceStatus",
]
