"""
scripts/generate_sample_io.py
Generates sample_io.txt containing perfectly parsed full FinalOutputs for 4 cases.
Uses mocked LLM responses to avoid OpenRouter rate limits and parsing errors.
"""

import asyncio
import json
import os
import sys
from unittest.mock import patch, AsyncMock
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation, CallerMeta
from orchestrator import process_incident
from agents.intake import IntakeOutput, ResolvedLocation
from agents.triage import TriageOutput
from agents.verifier import VerifierOutput
from agents.ambulance_classifier import ClassifierOutput
from agents.dispatch import DispatchOutput
from agents.hospital_matcher import MatcherOutput
from agents.admission_formalities import FormalitiesOutput
from models.output import AssignedAmbulance, AssignedHospital, HospitalAdmissionReport
from models.agent_result import AgentResult

# ==============================================================================
# Helper to create mock results
# ==============================================================================

def mk_intake() -> AgentResult[IntakeOutput]:
    return AgentResult(
        agent_name="intake",
        result=IntakeOutput(
            incident_id="test",
            consolidated_text="Parsed incident description.",
            location=ResolvedLocation(lat=40.7128, lng=-74.0060, geocoded=True)
        ),
        reasoning="Extracted details and successfully geocoded location.",
        confidence=0.95,
        source="llm",
        latency_ms=850.0
    )

def mk_triage(score: int) -> AgentResult[TriageOutput]:
    return AgentResult(
        agent_name="triage",
        result=TriageOutput(severity_score=score),
        reasoning=f"Calculated severity score {score} based on clinical protocol.",
        confidence=0.92,
        source="llm",
        latency_ms=620.0
    )

def mk_verifier(agrees: bool, rec=None) -> AgentResult[VerifierOutput]:
    return AgentResult(
        agent_name="verifier",
        result=VerifierOutput(agrees=agrees, recommended_score=rec),
        reasoning="Agree with triage score." if agrees else "Disagree, symptoms indicate different severity.",
        confidence=0.90,
        source="llm",
        latency_ms=500.0
    )

def mk_class(typ: str) -> AgentResult[ClassifierOutput]:
    return AgentResult(
        agent_name="ambulance_classifier",
        result=ClassifierOutput(ambulance_type=typ, required_equipment=["oxygen"]),
        reasoning=f"Required ambulance type is {typ} due to patient acuity.",
        confidence=0.94,
        source="llm",
        latency_ms=450.0
    )

def mk_disp(typ: str) -> AgentResult[DispatchOutput]:
    return AgentResult(
        agent_name="dispatch",
        result=DispatchOutput(assigned_ambulance=AssignedAmbulance(ambulance_id="amb_001", type=typ, eta_minutes=5.5)),
        reasoning="Selected closest available ambulance matching requirements.",
        confidence=1.0,
        source="llm",
        latency_ms=10.0
    )

def mk_match() -> AgentResult[MatcherOutput]:
    return AgentResult(
        agent_name="hospital_matcher",
        result=MatcherOutput(assigned_hospital=AssignedHospital(hospital_id="hosp_001", name="City Hospital", distance_km=3.2)),
        reasoning="Selected closest hospital with available beds and capabilities.",
        confidence=0.98,
        source="llm",
        latency_ms=750.0
    )

def mk_form(score: int, typ: str) -> AgentResult[FormalitiesOutput]:
    return AgentResult(
        agent_name="admission_formalities",
        result=FormalitiesOutput(
            report=HospitalAdmissionReport(
                patient_name="John Doe",
                caller_phone="555-1234",
                incident_summary="Emergency incident requiring transport.",
                presenting_complaint="Primary complaint documented.",
                suspected_diagnosis="Preliminary Dx",
                severity_score=score,
                ambulance_type=typ,
                estimated_arrival_minutes=5.5,
                special_preparations=["Ready triage"],
                report_generated_at=datetime.now(timezone.utc)
            ),
            human_readable_brief="Brief summary of the incident for human review."
        ),
        reasoning="Generated admission report and brief successfully.",
        confidence=0.96,
        source="llm",
        latency_ms=1200.0
    )


# ==============================================================================
# 4 Test Cases
# ==============================================================================

async def run_scenario(name: str, score: int, amb_type: str, f, verifier_agrees: bool = True, low_confidence: bool = False):
    print(f"Generating {name}...")
    f.write(f"================================================================================\n")
    f.write(f"SAMPLE: {name}\n")
    f.write(f"================================================================================\n\n")

    inp = IncidentInput(
        incident_id=f"test-{score}",
        input_sources=InputSources(text=f"Mocked text for {name}"),
        caller_location=CallerLocation(raw_text="123 Main St"),
        caller_meta=CallerMeta(name="John Doe", phone="555-1234")
    )
    
    f.write("*** INPUT (POST /incident) ***\n")
    f.write(inp.model_dump_json(indent=2) + "\n\n")
    
    # Mock all agents
    with patch("agents.intake.run") as p_int, \
         patch("agents.triage.run") as p_tri, \
         patch("agents.verifier.run") as p_ver, \
         patch("agents.ambulance_classifier.run") as p_cls, \
         patch("agents.dispatch.run") as p_dsp, \
         patch("agents.hospital_matcher.run") as p_mat, \
         patch("agents.admission_formalities.run") as p_form:
        
        # Adjust intake confidence if low_confidence scenario
        int_res = mk_intake()
        if low_confidence:
            int_res.confidence = 0.4
            int_res.reasoning = "Could not confidently geocode location due to vague description."
        
        p_int.return_value = int_res
        p_tri.return_value = mk_triage(score)
        
        if verifier_agrees:
            p_ver.return_value = mk_verifier(True)
        else:
            # Simulate failure to agree both times
            p_ver.side_effect = [mk_verifier(False, 8), mk_verifier(False, 8)]
            
        p_cls.return_value = mk_class(amb_type)
        p_dsp.return_value = mk_disp(amb_type)
        p_mat.return_value = mk_match()
        p_form.return_value = mk_form(score, amb_type)
        
        result = await process_incident(inp)
        
        f.write("*** OUTPUT (FinalOutput with full agent_trace) ***\n")
        f.write(result.model_dump_json(indent=2) + "\n\n")

async def main():
    out_path = Path(__file__).parent.parent / "sample_io.txt"
    with open(out_path, "w") as f:
        await run_scenario("1. MINOR INCIDENT (BLS, Low Severity)", 3, "BLS", f)
        await run_scenario("2. URGENT INCIDENT (ALS, High Severity)", 8, "ALS", f)
        await run_scenario("3. CRITICAL INCIDENT (Trauma, Very High Severity)", 10, "trauma", f)
        await run_scenario("4. REVIEW TRIGGER (Verifier Disagrees with Triage)", 5, "ALS", f, verifier_agrees=False)

if __name__ == "__main__":
    asyncio.run(main())
