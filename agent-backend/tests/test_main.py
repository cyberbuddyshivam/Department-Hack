"""
tests/test_main.py
Unit tests for main.py (FastAPI entry point)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from main import app
from models.output import FinalOutput, FinalDecision, AssignedAmbulance, AssignedHospital, HospitalAdmissionReport
from datetime import datetime, timezone

client = TestClient(app)

def make_mock_final_output(incident_id: str) -> FinalOutput:
    return FinalOutput(
        incident_id=incident_id,
        final_decision=FinalDecision(
            severity_score=8,
            ambulance=AssignedAmbulance(ambulance_id="a1", type="ALS", eta_minutes=5.0),
            hospital=AssignedHospital(hospital_id="h1", name="H1", distance_km=2.0),
            requires_human_review=False
        ),
        agent_trace=[],
        hospital_admission_report=HospitalAdmissionReport(
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
    )

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mock_store_loaded": True}

@patch("main.process_incident")
def test_post_incident_success(mock_process):
    # Setup mock
    incident_id = "test-123"
    mock_process.return_value = make_mock_final_output(incident_id)

    # Valid payload
    payload = {
        "incident_id": incident_id,
        "input_sources": {
            "text": "Help!"
        },
        "caller_location": {
            "raw_text": "123 Main St"
        },
        "caller_meta": {
            "name": "Bob",
            "phone": "555"
        }
    }

    response = client.post("/incident", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == incident_id
    assert data["final_decision"]["severity_score"] == 8

@patch("main.process_incident")
def test_post_incident_500_on_exception(mock_process):
    # Setup mock to raise Exception
    mock_process.side_effect = RuntimeError("Something blew up")

    payload = {
        "incident_id": "err-123",
        "input_sources": {"text": "Help!"},
        "caller_location": {"raw_text": "123 Main St"}
    }

    response = client.post("/incident", json=payload)
    
    assert response.status_code == 500
    assert "Something blew up" in response.json()["detail"]

def test_post_incident_422_on_invalid_input():
    # Missing required fields
    payload = {
        "incident_id": "err-123"
    }

    response = client.post("/incident", json=payload)
    
    # FastAPI automatic Pydantic validation error
    assert response.status_code == 422
