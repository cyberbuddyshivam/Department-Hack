from models.event import StandardEmergencyEvent
from config.settings import settings
import logging
import requests
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# In-memory store for frontend tracking
TRACKING_RESULTS = {}

class AgentDispatcher:
    def __init__(self, agent_api_url: str = "http://127.0.0.1:8001/incident/stream"):
        self.agent_api_url = agent_api_url

    def dispatch(self, event: StandardEmergencyEvent) -> bool:
        """
        Forwards the StandardEmergencyEvent to the downstream Multi-Agent AI system via SSE stream.
        """
        logger.info(f"Dispatching event {event.id} from {event.source} to Agent API Stream.")
        
        # Initialize tracking state
        TRACKING_RESULTS[event.id] = {
            "status": "processing",
            "agent_trace": [],
            "map_data": None,
            "hospital_report": None,
            "brief": None
        }

        # Map our StandardEmergencyEvent to the agent backend's IncidentInput
        
        # Extract coordinates securely from metadata
        lat = event.metadata.get("latitude")
        lng = event.metadata.get("longitude")
        location_str = event.metadata.get("location", "")
        
        if (lat is None or lng is None) and "," in location_str:
            try:
                parts = location_str.split(",")
                lat = float(parts[0].strip())
                lng = float(parts[1].strip())
            except ValueError:
                pass
                
        incident_input = {
            "incident_id": event.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_sources": {
                "text": event.message,
                "audio_transcript": None,
                "image_refs": event.attachments,
                "call_transcript": event.metadata.get("transcription")
            },
            "caller_location": {
                "lat": lat,
                "lng": lng,
                "raw_text": location_str or "Unknown"
            },
            "caller_meta": {
                "name": event.metadata.get("profile_name", "Unknown"),
                "phone": event.sender,
                "relation": "caller"
            }
        }
        
        try:
            # Stream the agent backend response
            with requests.post(self.agent_api_url, json=incident_input, stream=True) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[6:]
                            try:
                                data = json.loads(data_str)
                                if "final_decision" in data:
                                    # It's the FinalOutput
                                    TRACKING_RESULTS[event.id]["status"] = "completed"
                                    TRACKING_RESULTS[event.id]["map_data"] = data.get("map_data")
                                    TRACKING_RESULTS[event.id]["hospital_report"] = data.get("hospital_admission_report")
                                    TRACKING_RESULTS[event.id]["brief"] = data.get("human_readable_brief")
                                    
                                    # Overwrite the agent trace just to ensure consistency
                                    if "agent_trace" in data:
                                        TRACKING_RESULTS[event.id]["agent_trace"] = data.get("agent_trace")
                                else:
                                    # It's an AgentResult
                                    TRACKING_RESULTS[event.id]["agent_trace"].append(data)
                            except json.JSONDecodeError:
                                logger.error(f"Failed to parse SSE JSON: {data_str}")
                                
            logger.info(f"Successfully processed event {event.id} through agents stream.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to dispatch to agent backend: {e}")
            TRACKING_RESULTS[event.id]["status"] = "failed"
            return False

dispatcher = AgentDispatcher()
