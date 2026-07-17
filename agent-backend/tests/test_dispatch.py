"""
tests/test_dispatch.py
Unit tests for agents/dispatch.py — ai-workflow-rules.md §2 compliance.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.dispatch import run, DispatchInput
from agents.intake import ResolvedLocation
from models.ambulance import Ambulance

MOCK_SUCCESS = '{"selected_id": "amb_002", "confidence": 0.9, "reasoning": "Closest."}'
MOCK_MALFORMED = "I cannot determine."
MOCK_INVALID_ID = '{"selected_id": "amb_999", "confidence": 0.9, "reasoning": "Wrong."}'

def make_ambulance(amb_id, typ="ALS", lat=0.0, lng=0.0, equip=None):
    if equip is None:
        equip = ["oxygen", "cardiac_monitor", "stretcher"]
    return Ambulance(id=amb_id, type=typ, lat=lat, lng=lng, status="available", equipment=equip)

def make_input(incident_id="disp-01", typ="ALS", req_eq=None) -> DispatchInput:
    if req_eq is None:
        req_eq = []
    return DispatchInput(
        incident_id=incident_id,
        caller_location=ResolvedLocation(lat=0.1, lng=0.1, geocoded=False),
        ambulance_type=typ,
        required_equipment=req_eq
    )

@pytest.fixture(autouse=True)
def mock_store(monkeypatch):
    amb1 = make_ambulance("amb_001", "BLS", 10.0, 10.0)
    amb2 = make_ambulance("amb_002", "ALS", 0.11, 0.11)
    amb3 = make_ambulance("amb_003", "ALS", 0.5, 0.5)
    
    mock_get_avail = MagicMock(return_value=[amb1, amb2, amb3])
    monkeypatch.setattr("agents.dispatch.mock_store.get_available_ambulances", mock_get_avail)
    
    mock_assign = MagicMock(return_value=True)
    monkeypatch.setattr("agents.dispatch.mock_store.assign_ambulance", mock_assign)
    
    mock_get_assign = MagicMock(return_value={})
    monkeypatch.setattr("agents.dispatch.mock_store.get_assignment", mock_get_assign)
    
    mock_get_amb = MagicMock(return_value=amb2)
    monkeypatch.setattr("agents.dispatch.mock_store.get_ambulance", mock_get_amb)


@pytest.mark.asyncio
async def test_dispatch_llm_success():
    inp = make_input()
    with patch("agents.dispatch.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.assigned_ambulance.ambulance_id == "amb_002"
    assert result.result.assigned_ambulance.type == "ALS"


@pytest.mark.asyncio
async def test_dispatch_idempotent(monkeypatch):
    inp = make_input("disp-02")
    # Simulate already dispatched
    monkeypatch.setattr("agents.dispatch.mock_store.get_assignment", MagicMock(return_value={"ambulance_id": "amb_002"}))
    with patch("agents.dispatch.complete", new=AsyncMock()) as mock_complete:
        result = await run(inp)
    
    mock_complete.assert_not_called()
    assert result.source == "llm"
    assert result.result.assigned_ambulance.ambulance_id == "amb_002"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_dispatch_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.dispatch.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    # Should fallback to closest matching (amb_002)
    assert result.result.assigned_ambulance.ambulance_id == "amb_002"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_dispatch_invalid_id_fallback():
    inp = make_input()
    with patch("agents.dispatch.complete", new=AsyncMock(return_value=MOCK_INVALID_ID)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.assigned_ambulance.ambulance_id == "amb_002"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_dispatch_no_candidates(monkeypatch):
    inp = make_input(req_eq=["neonatal_incubator"]) # none have this in our mock
    # Should fallback to first available overall
    with patch("agents.dispatch.complete", new=AsyncMock()):
        result = await run(inp)
    
    assert result.source == "fallback"
    # Fallback no candidates picks first available globally: amb_001
    assert result.result.assigned_ambulance.ambulance_id == "amb_001"
    assert result.confidence <= 0.2
