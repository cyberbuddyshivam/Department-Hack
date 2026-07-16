from models.event import StandardEmergencyEvent
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

class AgentDispatcher:
    def __init__(self, agent_api_url: str = settings.AGENT_API_URL):
        self.agent_api_url = agent_api_url

    def dispatch(self, event: StandardEmergencyEvent) -> bool:
        """
        Forwards the StandardEmergencyEvent to the downstream Multi-Agent AI system.
        """
        logger.info(f"Dispatching event {event.id} from {event.source} to Agent API.")
        
        # Simulated HTTP request to the downstream multi-agent system
        # import requests
        # response = requests.post(self.agent_api_url, json=event.model_dump())
        # return response.status_code == 200
        
        print(f"\n--- DISPATCHED TO AGENT SYSTEM ---")
        print(event.model_dump_json(indent=2))
        print(f"----------------------------------\n")
        
        return True

dispatcher = AgentDispatcher()
