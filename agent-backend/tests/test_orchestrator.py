"""
tests/test_orchestrator.py
Unit tests for orchestrator.py — ai-workflow-rules.md §2 compliance.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from models.input import IncidentInput, CallerMeta, InputSources, CallerLocation
from models.output import AssignedAmbulance, AssignedHospital, HospitalAdmissionReport, FinalOutput
from models.agent_result import AgentResult

from orchestrator import process_incident
from agents import intake, triage, verifier, ambulance_classifier, dispatch, hospital_matcher, admission_formalities
from agents.intake import IntakeOutput, ResolvedLocation
from agents.triage import TriageOutput
from agents.verifier import VerifierOutput
from agents.ambulance_classifier import ClassifierOutput
from agents.dispatch import DispatchOutput
from agents.hospital_matcher import MatcherOutput
from agents.admission_formalities import FormalitiesOutput

# ---------------------------------------------------------------------------
# Mocks & Fixtures
# ---------------------------------------------------------------------------

def make_incident() -> IncidentInput:
    return IncidentInput(
        incident_id="test-orch-01",
        input_sources=InputSources(text="Help!"),
        caller_location=CallerLocation(raw_text="123 Main St"),
        caller_meta=CallerMeta(name="Bob", phone="555")
    )

def make_intake_result(conf=0.9) -> AgentResult[IntakeOutput]:
    return AgentResult(
        agent_name="intake",
        result=IntakeOutput(
            incident_id="test",
            consolidated_text="Help!",
            location=ResolvedLocation(lat=1.0, lng=1.0, geocoded=True)
        ),
        reasoning="mock",
        confidence=conf,
        source="llm",
        latency_ms=10.0
    )

def make_triage_result(score=8, conf=0.9) -> AgentResult[TriageOutput]:
    return AgentResult(
        agent_name="triage",
        result=TriageOutput(severity_score=score),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )

def make_verifier_result(agrees=True, conf=0.9) -> AgentResult[VerifierOutput]:
    return AgentResult(
        agent_name="verifier",
        result=VerifierOutput(agrees=agrees, recommended_score=None),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )

def make_class_result(conf=0.9) -> AgentResult[ClassifierOutput]:
    return AgentResult(
        agent_name="ambulance_classifier",
        result=ClassifierOutput(ambulance_type="ALS", required_equipment=[]),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )

def make_disp_result(conf=0.9) -> AgentResult[DispatchOutput]:
    return AgentResult(
        agent_name="dispatch",
        result=DispatchOutput(
            assigned_ambulance=AssignedAmbulance(ambulance_id="a1", type="ALS", eta_minutes=5.0)
        ),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )

def make_match_result(conf=0.9) -> AgentResult[MatcherOutput]:
    return AgentResult(
        agent_name="hospital_matcher",
        result=MatcherOutput(
            assigned_hospital=AssignedHospital(hospital_id="h1", name="H1", distance_km=2.0)
        ),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )

def make_form_result(conf=0.9) -> AgentResult[FormalitiesOutput]:
    return AgentResult(
        agent_name="admission_formalities",
        result=FormalitiesOutput(
            report=HospitalAdmissionReport(
                patient_name="Bob",
                caller_phone="555",
                incident_summary="Test",
                presenting_complaint="Test",
                suspected_diagnosis=None,
                severity_score=8,
                ambulance_type="ALS",
                estimated_arrival_minutes=5.0,
                special_preparations=[],
                report_generated_at=datetime.now(timezone.utc)
            ),
            human_readable_brief="Test brief"
        ),
        reasoning="mock", confidence=conf, source="llm", latency_ms=10.0
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_agents(monkeypatch):
    monkeypatch.setattr("agents.intake.run", AsyncMock(return_value=make_intake_result()))
    monkeypatch.setattr("agents.triage.run", AsyncMock(return_value=make_triage_result()))
    monkeypatch.setattr("agents.verifier.run", AsyncMock(return_value=make_verifier_result()))
    monkeypatch.setattr("agents.ambulance_classifier.run", AsyncMock(return_value=make_class_result()))
    monkeypatch.setattr("agents.dispatch.run", AsyncMock(return_value=make_disp_result()))
    monkeypatch.setattr("agents.hospital_matcher.run", AsyncMock(return_value=make_match_result()))
    monkeypatch.setattr("agents.admission_formalities.run", AsyncMock(return_value=make_form_result()))


@pytest.mark.asyncio
async def test_orchestrator_success_no_review():
    inp = make_incident()
    res = await process_incident(inp)
    
    # 1(intake) + 1(triage) + 1(verifier) + 1(class) + 2(disp,match) + 1(form) = 7
    assert len(res.agent_trace) == 7
    assert res.final_decision.requires_human_review is False


@pytest.mark.asyncio
async def test_orchestrator_low_confidence_triggers_review(monkeypatch):
    # Mock intake with low confidence
    monkeypatch.setattr("agents.intake.run", AsyncMock(return_value=make_intake_result(conf=0.3)))
    
    inp = make_incident()
    res = await process_incident(inp)
    
    assert res.final_decision.requires_human_review is True


@pytest.mark.asyncio
async def test_orchestrator_verifier_loop_resolves(monkeypatch):
    # Verifier disagrees first time, agrees second time
    mock_verifier = AsyncMock(side_effect=[
        make_verifier_result(agrees=False),
        make_verifier_result(agrees=True)
    ])
    monkeypatch.setattr("agents.verifier.run", mock_verifier)
    
    inp = make_incident()
    res = await process_incident(inp)
    
    # Trace will have 1 extra triage and 1 extra verifier = 9 total
    assert len(res.agent_trace) == 9
    assert res.final_decision.requires_human_review is False


@pytest.mark.asyncio
async def test_orchestrator_verifier_loop_fails_triggers_review(monkeypatch):
    # Verifier disagrees both times
    mock_verifier = AsyncMock(side_effect=[
        make_verifier_result(agrees=False),
        make_verifier_result(agrees=False)
    ])
    monkeypatch.setattr("agents.verifier.run", mock_verifier)
    
    inp = make_incident()
    res = await process_incident(inp)
    
    assert len(res.agent_trace) == 9
    assert res.final_decision.requires_human_review is True
