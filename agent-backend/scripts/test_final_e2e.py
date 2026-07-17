import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.input import IncidentInput, InputSources, CallerLocation
from orchestrator import process_incident

logging.basicConfig(level=logging.WARNING, format='%(message)s')

async def main():
    inp = IncidentInput(
        incident_id="test-final-1",
        input_sources=InputSources(text="Severe chest pain radiating to left arm, sweating heavily, difficulty breathing for the last 15 minutes."),
        caller_location=CallerLocation(lat=19.1172, lng=72.8340)
    )
    
    result = await process_incident(inp)
    print("\n=== FINAL OUTPUT JSON ===")
    print(result.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(main())
