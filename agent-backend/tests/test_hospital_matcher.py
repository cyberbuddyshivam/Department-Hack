"""
tests/test_hospital_matcher.py
Unit tests for agents/hospital_matcher.py — ai-workflow-rules.md §2 compliance.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.hospital_matcher import run, MatcherInput
from agents.intake import ResolvedLocation
from models.hospital import Hospital

MOCK_SUCCESS = '{"selected_id": "hosp_002", "confidence": 0.9, "reasoning": "Closest with beds."}'
MOCK_MALFORMED = "I cannot determine."
MOCK_INVALID_ID = '{"selected_id": "hosp_999", "confidence": 0.9, "reasoning": "Wrong."}'

def make_hospital(hosp_id, name="Hosp", lat=0.0, lng=0.0, beds=10, trauma=False, specialties=None, icu=True):
    if specialties is None:
        specialties = ["general_emergency"]
    return Hospital(
        id=hosp_id, name=name, lat=lat, lng=lng, available_beds=beds, total_beds=beds,
        has_trauma_center=trauma, specialties=specialties, has_icu=icu
    )

def make_input(incident_id="match-01", typ="ALS", sev=5) -> MatcherInput:
    return MatcherInput(
        incident_id=incident_id,
        caller_location=ResolvedLocation(lat=0.1, lng=0.1, geocoded=False),
        consolidated_text="Test incident",
        severity_score=sev,
        ambulance_type=typ,
    )

@pytest.fixture(autouse=True)
def mock_store(monkeypatch):
    h1 = make_hospital("hosp_001", beds=10, trauma=False, specialties=["general_emergency"])
    h2 = make_hospital("hosp_002", beds=5, trauma=True, specialties=["general_emergency", "trauma_surgery"])
    h3 = make_hospital("hosp_003", beds=2, trauma=False, specialties=["neonatal_icu"])
    
    mock_get_avail = MagicMock(return_value=[h1, h2, h3])
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_hospitals_with_available_beds", mock_get_avail)
    
    mock_get_all = MagicMock(return_value=[h1, h2, h3])
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_all_hospitals", mock_get_all)
    
    mock_assign = MagicMock(return_value=True)
    monkeypatch.setattr("agents.hospital_matcher.mock_store.assign_hospital_bed", mock_assign)
    
    mock_get_assign = MagicMock(return_value={})
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_assignment", mock_get_assign)
    
    mock_get_hosp = MagicMock(return_value=h2)
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_hospital", mock_get_hosp)


@pytest.mark.asyncio
async def test_matcher_llm_success():
    inp = make_input()
    with patch("agents.hospital_matcher.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.assigned_hospital.hospital_id == "hosp_002"


@pytest.mark.asyncio
async def test_matcher_idempotent(monkeypatch):
    inp = make_input("match-02")
    # Simulate already dispatched
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_assignment", MagicMock(return_value={"hospital_id": "hosp_002"}))
    with patch("agents.hospital_matcher.complete", new=AsyncMock()) as mock_complete:
        result = await run(inp)
    
    mock_complete.assert_not_called()
    assert result.source == "llm"
    assert result.result.assigned_hospital.hospital_id == "hosp_002"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_matcher_trauma_filter():
    inp = make_input(typ="trauma")
    # LLM returns hosp_002, which is correct
    with patch("agents.hospital_matcher.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.result.assigned_hospital.hospital_id == "hosp_002"


@pytest.mark.asyncio
async def test_matcher_neonatal_filter():
    inp = make_input(typ="neonatal")
    # LLM success string returns "hosp_002", but hosp_002 should NOT be in the candidates!
    # Because only hosp_003 has neonatal_icu. If LLM returns hosp_002, it raises ValueError and falls back to top_candidates[0] which is hosp_003
    with patch("agents.hospital_matcher.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    # It fell back because selected_id was invalid
    assert result.source == "fallback"
    assert result.result.assigned_hospital.hospital_id == "hosp_003"


@pytest.mark.asyncio
async def test_matcher_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.hospital_matcher.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.assigned_hospital.hospital_id == "hosp_001"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_matcher_invalid_id_fallback():
    inp = make_input()
    with patch("agents.hospital_matcher.complete", new=AsyncMock(return_value=MOCK_INVALID_ID)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.assigned_hospital.hospital_id == "hosp_001"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_matcher_no_candidates(monkeypatch):
    # Simulate no beds available globally
    monkeypatch.setattr("agents.hospital_matcher.mock_store.get_hospitals_with_available_beds", MagicMock(return_value=[]))
    inp = make_input()
    
    with patch("agents.hospital_matcher.complete", new=AsyncMock()):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.assigned_hospital.hospital_id == "hosp_001" # pulls from get_all_hospitals[0]
    assert result.confidence <= 0.2
