"""
scripts/run_e2e.py
AEGIS — End-to-End Test Script (Step 12)

Runs the orchestrator against 3 realistic sample incidents representing different
acuity levels (minor, urgent, critical) using the live OpenRouter gateway.
"""

import asyncio
import json
import logging
from pprint import pprint

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation, CallerMeta
from orchestrator import process_incident

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("e2e")

# We turn off debug logging for the gateway to keep the console clean
logging.getLogger("llm_gateway").setLevel(logging.WARNING)

INCIDENTS = [
    {
        "id": "e2e-minor-01",
        "desc": "My son twisted his ankle playing soccer at the community park on Elm St. It's swelling up but he is conscious and breathing fine.",
        "name": "Jane Smith",
        "phone": "555-0101",
        "expected": "BLS, low severity"
    },
    {
        "id": "e2e-urgent-02",
        "desc": "I am having really bad chest pains. It feels like an elephant is sitting on my chest and I can't catch my breath. I am at 400 West Ave.",
        "name": "Robert Johnson",
        "phone": "555-0202",
        "expected": "ALS, high severity, ICU"
    },
    {
        "id": "e2e-critical-03",
        "desc": "Massive car crash on the interstate junction! Multiple cars involved. One person is bleeding heavily from their head and isn't moving. Please hurry!",
        "name": "Anonymous Bystander",
        "phone": "555-0303",
        "expected": "trauma, very high severity, trauma center"
    }
]


async def run_incident(inc_data: dict):
    print(f"\n{'='*80}")
    print(f"STARTING INCIDENT: {inc_data['id']} (Expected: {inc_data['expected']})")
    print(f"{'='*80}")
    
    inp = IncidentInput(
        incident_id=inc_data["id"],
        input_sources=InputSources(text=inc_data["desc"]),
        caller_location=CallerLocation(raw_text=inc_data["desc"]),
        caller_meta=CallerMeta(name=inc_data["name"], phone=inc_data["phone"])
    )
    
    result = await process_incident(inp)
    
    print("\nPIPELINE COMPLETE")
    print("-" * 40)
    print("FINAL DECISION (Machine Readable):")
    print(json.dumps(result.final_decision.model_dump(), indent=2))
    
    print("-" * 40)
    print("HUMAN READABLE BRIEF:")
    print(result.human_readable_brief)
    
    print("-" * 40)
    print("HOSPITAL ADMISSION REPORT (Preview):")
    print(f"Complaint: {result.hospital_admission_report.presenting_complaint}")
    print(f"Preparations: {result.hospital_admission_report.special_preparations}")
    
    print("-" * 40)
    print(f"TRACE AUDIT ({len(result.agent_trace)} steps):")
    for step in result.agent_trace:
        print(f"  - [{step.agent_name}] Conf: {step.confidence:.2f} | Latency: {step.latency_ms}ms | Reasoning: {step.reasoning}")


async def main():
    print("Starting AEGIS End-to-End tests...\n")
    for idx, inc in enumerate(INCIDENTS):
        if idx > 0:
            print("\nWaiting 10 seconds to respect API rate limits...")
            await asyncio.sleep(10)
        
        try:
            await run_incident(inc)
        except Exception as e:
            logger.error("Failed to run incident %s: %s", inc['id'], e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
