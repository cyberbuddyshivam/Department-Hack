import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation
from orchestrator import process_incident

logging.basicConfig(level=logging.WARNING, format='%(message)s')

async def check(name, lat, lng):
    inp = IncidentInput(
        incident_id=f"test-{name.replace(' ', '')}",
        input_sources=InputSources(text="Severe chest pain, heart attack."),
        caller_location=CallerLocation(lat=lat, lng=lng)
    )
    res = await process_incident(inp)
    eta = res.final_decision.ambulance.eta_minutes
    dist = res.final_decision.hospital.distance_km
    amb_id = res.final_decision.ambulance.ambulance_id
    hosp_id = res.final_decision.hospital.hospital_id
    print(f"[{name}]")
    print(f"  Ambulance: {amb_id} (ETA: {eta} min)")
    print(f"  Hospital:  {hosp_id} (Dist: {dist} km)\n")

async def main():
    print("=== ETA SPOT CHECK ===")
    await check("Pune (Koregaon Park)", 18.5362, 73.8939)
    await check("Nashik (Panchavati)", 20.0110, 73.7902)
    await check("Thane (Majiwada)", 19.2183, 72.9781)
    
if __name__ == "__main__":
    asyncio.run(main())
