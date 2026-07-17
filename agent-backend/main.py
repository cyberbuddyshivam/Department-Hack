"""
main.py
AEGIS — FastAPI entry point (Step 11 in build order)

Exposes the POST /incident endpoint which triggers the AEGIS orchestrator.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import logging

from models.input import IncidentInput
from models.output import FinalOutput
from orchestrator import process_incident, process_incident_stream
from data import mock_store

# Configure global logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AEGIS Emergency Routing API",
    description="Agentic Emergency Grade Intelligent System (Phase 1)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (e.g., localhost, Vercel)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "mock_store_loaded": True}

@app.post("/incident", response_model=FinalOutput)
async def handle_incident(incident: IncidentInput):
    """
    Ingest a multimodal emergency incident.
    Returns a FinalOutput containing the decision, admission report, and full agent audit trace.
    """
    logger.info("Received POST /incident for ID: %s", incident.incident_id)
    
    # Check if this incident has already been processed (idempotency at top level)
    if mock_store.is_duplicate_incident(incident.incident_id):
        logger.info("Incident %s is a known duplicate but we process idempotently inside the pipeline.", incident.incident_id)

    try:
        result = await process_incident(incident)
        logger.info("Successfully processed incident %s. Severity: %d, Ambulance: %s, Hospital: %s", 
                    incident.incident_id, 
                    result.final_decision.severity_score,
                    result.final_decision.ambulance.ambulance_id,
                    result.final_decision.hospital.hospital_id)
        return result
    except Exception as exc:
        logger.error("Unhandled exception processing incident %s: %s", incident.incident_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {exc}")


@app.post("/incident/stream")
async def handle_incident_stream(incident: IncidentInput):
    """
    Ingest a multimodal emergency incident and stream intermediate agent events via SSE.
    """
    logger.info("Received POST /incident/stream for ID: %s", incident.incident_id)
    
    # Check if this incident has already been processed (idempotency at top level)
    if mock_store.is_duplicate_incident(incident.incident_id):
        logger.info("Incident %s is a known duplicate but we process idempotently inside the pipeline.", incident.incident_id)

    async def event_generator():
        try:
            async for event in process_incident_stream(incident):
                yield f"data: {event.model_dump_json()}\n\n"
        except Exception as exc:
            logger.error("Unhandled exception processing incident stream %s: %s", incident.incident_id, exc, exc_info=True)
            yield f'data: {{"error": "Internal Server Error: {str(exc)}"}}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")
