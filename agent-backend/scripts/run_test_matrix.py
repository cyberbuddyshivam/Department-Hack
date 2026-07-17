import asyncio
import json
from models.input import IncidentInput, InputSources, CallerLocation
from orchestrator import process_incident
from data import mock_store

async def run_case(name, input_args):
    # Reset state to avoid running out of ambulances
    mock_store._ambulances = mock_store._load_ambulances()
    mock_store._hospitals = mock_store._load_hospitals()
    mock_store._dedup_store.clear()
    print(f"\n### {name}\n```json")
    inc = IncidentInput(**input_args)
    try:
        out = await process_incident(inc)
        print(out.model_dump_json(indent=2))
    except Exception as e:
        print(f"FAILED WITH EXCEPTION: {e}")
    print("```\n")

async def main():
    # 1. Text-only
    await run_case("1. Text-only incident report", {
        "incident_id": "case-1",
        "input_sources": InputSources(text="Severe burn on right arm from chemical spill, conscious but in extreme pain."),
        "caller_location": CallerLocation(lat=19.1, lng=72.8)
    })
    
    # 2. Audio input (garbled)
    await run_case("2. Audio input (garbled/background noise)", {
        "incident_id": "case-2",
        "input_sources": InputSources(audio_transcript="uhh hello? yeah um please send someone... a guy just uh fell I think... lot of... um... noise..."),
        "caller_location": CallerLocation(lat=19.11, lng=72.81)
    })
    
    # 3. Image input
    await run_case("3. Image input", {
        "incident_id": "case-3",
        "input_sources": InputSources(image_refs=["https://example.com/huge_fire.jpg"]),
        "caller_location": CallerLocation(lat=19.12, lng=72.82)
    })
    
    # 4. Mixed input
    await run_case("4. Mixed input", {
        "incident_id": "case-4",
        "input_sources": InputSources(
            call_transcript="Caller states it's just a minor cut on the finger.",
            text="Patient's photo shows heavy arterial bleeding.",
            image_refs=["https://example.com/arterial_bleed.jpg"]
        ),
        "caller_location": CallerLocation(lat=19.13, lng=72.83)
    })
    
    # 5. Severity 1-2
    await run_case("5. Severity 1-2 (trivial)", {
        "incident_id": "case-5",
        "input_sources": InputSources(text="Stubbed toe, no bleeding, patient can walk fine but wants it checked out."),
        "caller_location": CallerLocation(lat=19.14, lng=72.84)
    })
    
    # 6. Severity 5-6
    await run_case("6. Severity 5-6 (ambiguous/moderate)", {
        "incident_id": "case-6",
        "input_sources": InputSources(text="Fell off bicycle, arm looks swollen and might be fractured, in moderate pain."),
        "caller_location": CallerLocation(lat=19.15, lng=72.85)
    })
    
    # 7. Severity 9-10
    await run_case("7. Severity 9-10 (critical)", {
        "incident_id": "case-7",
        "input_sources": InputSources(text="Unconscious and not breathing after a major high-speed car crash. Need immediate help."),
        "caller_location": CallerLocation(lat=19.16, lng=72.86)
    })
    
    # 8. Malformed input
    await run_case("8. Malformed/nonsensical input", {
        "incident_id": "case-8",
        "input_sources": InputSources(text="asdfasdfasdf jjjkll"),
        "caller_location": CallerLocation(lat=19.17, lng=72.87)
    })
    
    # 9. Concurrent submissions
    print("\n### 9. Two incidents submitted concurrently\n```json")
    mock_store._ambulances = mock_store._load_ambulances()
    mock_store._hospitals = mock_store._load_hospitals()
    mock_store._dedup_store.clear()
    c9a = IncidentInput(
        incident_id="case-9a",
        input_sources=InputSources(text="Massive heart attack, clutching chest."),
        caller_location=CallerLocation(lat=19.01, lng=72.81)
    )
    c9b = IncidentInput(
        incident_id="case-9b",
        input_sources=InputSources(text="Minor paper cut."),
        caller_location=CallerLocation(lat=19.02, lng=72.82)
    )
    out_a, out_b = await asyncio.gather(process_incident(c9a), process_incident(c9b))
    print(out_a.model_dump_json(indent=2))
    print("\n")
    print(out_b.model_dump_json(indent=2))
    print("```\n")

if __name__ == "__main__":
    asyncio.run(main())
