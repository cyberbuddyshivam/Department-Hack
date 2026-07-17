"""
tests/test_verifier.py
Unit tests for agents/verifier.py — ai-workflow-rules.md §2 compliance.

Coverage matrix:
  - LLM success (agrees)
  - LLM success (disagrees, provides valid recommended score)
  - LLM parse error fallback
  - LLM disagree with invalid score fallback
  - LLM gateway error fallback
  - AgentResult envelope invariants
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agents.verifier import run, VerifierInput, VerifierOutput
from models.agent_result import AgentResult


# ---------------------------------------------------------------------------
# Fixtures & Mocks
# ---------------------------------------------------------------------------

def make_input(text="Test incident.", triage_score=5) -> VerifierInput:
    return VerifierInput(
        incident_id="verifier-test-01",
        consolidated_text=text,
        triage_severity_score=triage_score,
    )


MOCK_AGREES = '{"agrees": true, "recommended_score": null, "confidence": 0.9, "reasoning": "Looks good."}'
MOCK_DISAGREES = '{"agrees": false, "recommended_score": 8, "confidence": 0.8, "reasoning": "Too low."}'
MOCK_MALFORMED = "I cannot determine."
MOCK_DISAGREE_INVALID_SCORE = '{"agrees": false, "recommended_score": 15, "confidence": 0.8, "reasoning": "High."}'
MOCK_DISAGREE_MISSING_SCORE = '{"agrees": false, "confidence": 0.8, "reasoning": "No score."}'


# ---------------------------------------------------------------------------
# 1. LLM Success Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_llm_agrees():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_AGREES)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.agrees is True
    assert result.result.recommended_score is None
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_verifier_llm_disagrees():
    inp = make_input(triage_score=4)
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_DISAGREES)):
        result = await run(inp)
    
    assert result.source == "llm"
    assert result.result.agrees is False
    assert result.result.recommended_score == 8
    assert result.confidence == 0.8


# ---------------------------------------------------------------------------
# 2. Fallback Paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_llm_parse_error_fallback():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_MALFORMED)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.agrees is True
    assert result.result.recommended_score is None
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_verifier_llm_disagree_invalid_score_fallback():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_DISAGREE_INVALID_SCORE)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.agrees is True
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_verifier_llm_disagree_missing_score_fallback():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_DISAGREE_MISSING_SCORE)):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.agrees is True
    assert result.confidence <= 0.4


@pytest.mark.asyncio
async def test_verifier_llm_gateway_error_fallback():
    from llm_gateway import LLMGatewayError
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(side_effect=LLMGatewayError("timeout"))):
        result = await run(inp)
    
    assert result.source == "fallback"
    assert result.result.agrees is True
    assert result.confidence <= 0.4


# ---------------------------------------------------------------------------
# 3. AgentResult Invariants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_agent_name():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_AGREES)):
        result = await run(inp)
    assert result.agent_name == "verifier"


@pytest.mark.asyncio
async def test_verifier_latency_positive():
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=MOCK_AGREES)):
        result = await run(inp)
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_verifier_confidence_capped():
    high_conf = '{"agrees": true, "recommended_score": null, "confidence": 1.0, "reasoning": "Sure."}'
    inp = make_input()
    with patch("agents.verifier.complete", new=AsyncMock(return_value=high_conf)):
        result = await run(inp)
    assert result.confidence <= 0.95
