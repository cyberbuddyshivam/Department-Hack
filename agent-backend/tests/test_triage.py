"""
tests/test_triage.py
Unit tests for agents/triage.py — ai-workflow-rules.md §2 compliance.

Coverage matrix:
  - LLM success (clean JSON)
  - LLM success (markdown fenced JSON)
  - LLM parse error fallback
  - LLM invalid score fallback (out of bounds, wrong type)
  - LLM gateway error fallback
  - AgentResult envelope invariants
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agents.triage import run, TriageInput, TriageOutput
from models.agent_result import AgentResult


# ---------------------------------------------------------------------------
# Fixtures & Mocks
# ---------------------------------------------------------------------------

def make_input(text="Patient has severe chest pain and shortness of breath.") -> TriageInput:
    return TriageInput(incident_id="triage-test-01", consolidated_text=text)


MOCK_SUCCESS = '{"severity_score": 8, "confidence": 0.9, "reasoning": "Severe chest pain."}'
MOCK_FENCED = '```json\n{"severity_score": 2, "confidence": 0.8, "reasoning": "Minor cut."}\n```'
MOCK_MALFORMED = "I cannot determine the score."
MOCK_OUT_OF_BOUNDS = '{"severity_score": 15, "confidence": 0.9, "reasoning": "Too high."}'
MOCK_INVALID_TYPE = '{"severity_score": "high", "confidence": 0.9, "reasoning": "String."}'


# ---------------------------------------------------------------------------
# 1. LLM Success Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_llm_success():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.severity_score == 8
    assert result.confidence == 0.9
    assert result.reasoning == "Severe chest pain."


@pytest.mark.asyncio
async def test_triage_llm_success_fenced_json():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_FENCED)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.severity_score == 2
    assert result.confidence == 0.8
    assert result.reasoning == "Minor cut."


# ---------------------------------------------------------------------------
# 2. Fallback Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.severity_score == 5
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_triage_llm_invalid_score_out_of_bounds_fallback():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_OUT_OF_BOUNDS)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.severity_score == 5
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_triage_llm_invalid_score_type_fallback():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_INVALID_TYPE)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.severity_score == 5
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_triage_llm_gateway_error_fallback():
    from llm_gateway import LLMGatewayError
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(side_effect=LLMGatewayError("rate limit"))):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.severity_score == 5
    assert result.confidence <= 0.4


# ---------------------------------------------------------------------------
# 3. AgentResult Invariants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_agent_name():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    assert result.agent_name == "triage"


@pytest.mark.asyncio
async def test_triage_latency_positive():
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=MOCK_SUCCESS)):
        result = await run(inp)
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_triage_high_confidence_cap():
    """Even if model returns 1.0, we cap at 0.95."""
    high_conf_mock = '{"severity_score": 10, "confidence": 1.0, "reasoning": "Absolutely sure."}'
    inp = make_input()
    with patch("agents.triage.complete", new=AsyncMock(return_value=high_conf_mock)):
        result = await run(inp)
    assert result.confidence <= 0.95
