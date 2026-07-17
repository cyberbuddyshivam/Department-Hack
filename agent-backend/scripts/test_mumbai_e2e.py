import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation, CallerMeta
from orchestrator import process_incident

logging.basicConfig(level=logging.WARNING, format='%(message)s')

async def test_location(location_name: str, incident_id: str):
    print(f"\n==============================================")
    print(f"TESTING LOCATION: {location_name}")
    print(f"==============================================\n")
    
    inp = IncidentInput(
        incident_id=incident_id,
        input_sources=InputSources(text=f"Massive car crash! Severe injuries."),
        caller_location=CallerLocation(raw_text=location_name),
        caller_meta=CallerMeta(name="Tester", phone="555")
    )
    
    result = await process_incident(inp)
    
    intake = next((t for t in result.agent_trace if t.agent_name == "intake"), None)
    dispatch = next((t for t in result.agent_trace if t.agent_name == "dispatch"), None)
    matcher = next((t for t in result.agent_trace if t.agent_name == "hospital_matcher"), None)
    
    if intake:
        loc = intake.result.location
        print(f"Geocoded Location: ({loc.lat}, {loc.lng}) via {intake.source}")
        print(f"Reasoning: {intake.reasoning}\n")
    
    if dispatch:
        amb = dispatch.result.assigned_ambulance
        print(f"Assigned Ambulance: {amb.ambulance_id} (Type: {amb.type})")
        print(f"ETA: {amb.eta_minutes} minutes")
        print(f"Reasoning: {dispatch.reasoning}\n")
        
    if matcher:
        hosp = matcher.result.assigned_hospital
        print(f"Assigned Hospital: {hosp.hospital_id} - {hosp.name}")
        print(f"Distance: {hosp.distance_km} km")
        print(f"Reasoning: {matcher.reasoning}\n")


async def main():
    # We add a slight delay between runs just in case, but Nominatim is only called once per incident
    await test_location("Andheri West, Mumbai", "mumbai-1")
    await asyncio.sleep(1.0)
    await test_location("Shivajinagar, Pune", "pune-1")

if __name__ == "__main__":
    asyncio.run(main())
