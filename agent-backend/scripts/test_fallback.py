"""
scripts/test_fallback.py
Demonstrates the pipeline's fallback mechanism by mocking llm_gateway to fail.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation, CallerMeta
from orchestrator import process_incident
from llm_gateway import LLMGatewayError

async def main():
    inp = IncidentInput(
        incident_id="fallback-test",
        input_sources=InputSources(text="Someone is hurt at the park."),
        caller_location=CallerLocation(raw_text="The park"),
        caller_meta=CallerMeta(name="Tester", phone="555")
    )
    
    # We will mock the gateway to always fail with a simulated timeout error
    with patch("agents.intake.complete", new=AsyncMock(side_effect=LLMGatewayError("Simulated LLM Timeout"))):
        print("Running orchestrator with simulated LLM timeout at Intake Agent...")
        result = await process_incident(inp)
        
        # Find the intake agent trace
        intake_trace = next((t for t in result.agent_trace if t.agent_name == "intake"), None)
        if intake_trace:
            print("\n*** Intake Agent Trace Entry ***")
            print(json.dumps(intake_trace.model_dump(), indent=2))
        else:
            print("Intake trace not found!")

if __name__ == "__main__":
    asyncio.run(main())
