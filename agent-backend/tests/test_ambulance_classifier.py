"""
tests/test_ambulance_classifier.py
Unit tests for agents/ambulance_classifier.py — ai-workflow-rules.md §2 compliance.

Coverage matrix:
  - LLM success (clean JSON, valid type/equipment)
  - LLM success (fenced JSON)
  - LLM filters invalid equipment gracefully
  - LLM parse error fallback
  - LLM invalid ambulance type fallback
  - LLM gateway error fallback
  - AgentResult envelope invariants
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agents.ambulance_classifier import run, ClassifierInput, ClassifierOutput
from models.agent_result import AgentResult


# ---------------------------------------------------------------------------
# Fixtures & Mocks
# ---------------------------------------------------------------------------

def make_input(text="Test incident.", severity=8) -> ClassifierInput:
    return ClassifierInput(
        incident_id="class-test-01",
        consolidated_text=text,
        severity_score=severity,
    )


MOCK_SUCCESS = '{"ambulance_type": "ALS", "required_equipment": ["oxygen", "cardiac_monitor"], "confidence": 0.9, "reasoning": "Standard ALS response."}'
MOCK_FENCED = '```json\n{"ambulance_type": "trauma", "required_equipment": ["blood_products"], "confidence": 0.95, "reasoning": "Trauma response."}\n```'
MOCK_INVALID_EQ = '{"ambulance_type": "BLS", "required_equipment": ["oxygen", "fake_magic_wand"], "confidence": 0.9, "reasoning": "BLS."}'
MOCK_INVALID_TYPE = '{"ambulance_type": "HELICOPTER", "required_equipment": [], "confidence": 0.9, "reasoning": "Need air support."}'
MOCK_MALFORMED = "I cannot determine."


# ---------------------------------------------------------------------------
# 1. LLM Success Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classifier_llm_success():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.ambulance_type == "ALS"
    assert "oxygen" in result.result.required_equipment
    assert "cardiac_monitor" in result.result.required_equipment
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_classifier_llm_success_fenced():
    inp = make_input(severity=10)
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_FENCED)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.ambulance_type == "trauma"
    assert "blood_products" in result.result.required_equipment


@pytest.mark.asyncio
async def test_classifier_filters_invalid_equipment():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_INVALID_EQ)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.ambulance_type == "BLS"
    assert "oxygen" in result.result.required_equipment
    assert "fake_magic_wand" not in result.result.required_equipment


# ---------------------------------------------------------------------------
# 2. Fallback Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classifier_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.ambulance_type == "ALS"
    assert result.result.required_equipment == []
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_classifier_llm_invalid_type_fallback():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_INVALID_TYPE)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.ambulance_type == "ALS"
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_classifier_llm_gateway_error_fallback():
    from llm_gateway import LLMGatewayError
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(side_effect=LLMGatewayError("timeout"))):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.ambulance_type == "ALS"
    assert result.confidence <= 0.4


# ---------------------------------------------------------------------------
# 3. AgentResult Invariants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classifier_agent_name():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    assert result.agent_name == "ambulance_classifier"


@pytest.mark.asyncio
async def test_classifier_latency_positive():
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_classifier_confidence_capped():
    high_conf = '{"ambulance_type": "ALS", "required_equipment": [], "confidence": 1.0, "reasoning": "Sure."}'
    inp = make_input()
    with patch("agents.ambulance_classifier.complete", new=AsyncMock(return_value=high_conf)):
        result = await run(inp)
    assert result.confidence <= 0.95
