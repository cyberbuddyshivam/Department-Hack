"""
tests/test_admission_formalities.py
Unit tests for agents/admission_formalities.py — ai-workflow-rules.md §2 compliance.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agents.admission_formalities import run, FormalitiesInput
from models.output import AssignedAmbulance, AssignedHospital


MOCK_SUCCESS = '''
{
  "incident_summary": "Patient hit by car.",
  "presenting_complaint": "Severe leg pain and bleeding.",
  "suspected_diagnosis": "Fractured femur.",
  "special_preparations": ["Activate trauma team"],
  "human_readable_brief": "A 30-year-old was hit by a car. Dispatched ALS.",
  "confidence": 0.9,
  "reasoning": "Standard trauma response."
}
'''
MOCK_MALFORMED = "I cannot determine."
MOCK_MISSING_FIELDS = '{"incident_summary": "Patient hit by car."}'


def make_input() -> FormalitiesInput:
    return FormalitiesInput(
        incident_id="form-01",
        consolidated_text="Patient hit by car, severe leg pain.",
        patient_name="John Doe",
        caller_phone="555-1234",
        severity_score=8,
        ambulance=AssignedAmbulance(ambulance_id="amb_001", type="ALS", eta_minutes=5.0),
        hospital=AssignedHospital(hospital_id="hosp_001", name="City Hospital", distance_km=2.5)
    )


@pytest.mark.asyncio
async def test_formalities_llm_success():
    inp = make_input()
    with patch("agents.admission_formalities.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.report.incident_summary == "Patient hit by car."
    assert result.result.report.presenting_complaint == "Severe leg pain and bleeding."
    assert result.result.human_readable_brief == "A 30-year-old was hit by a car. Dispatched ALS."
    assert result.result.report.patient_name == "John Doe"
    assert result.result.report.report_generated_at is not None
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_formalities_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.admission_formalities.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.report.incident_summary == "Emergency incident (LLM processing failed)."
    assert result.result.report.presenting_complaint.startswith("Patient hit by car")
    assert "LLM failure" in result.result.human_readable_brief
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_formalities_missing_fields_fallback():
    inp = make_input()
    with patch("agents.admission_formalities.complete", new=AsyncMock(return_value=MOCK_MISSING_FIELDS)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_formalities_gateway_error_fallback():
    from llm_gateway import LLMGatewayError
    inp = make_input()
    with patch("agents.admission_formalities.complete", new=AsyncMock(side_effect=LLMGatewayError("timeout"))):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_formalities_agent_name():
    inp = make_input()
    with patch("agents.admission_formalities.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    assert result.agent_name == "admission_formalities"
