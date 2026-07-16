from pydantic import BaseModel
from adapters.base import BaseAdapter
from models.event import StandardEmergencyEvent
from normalizer.core import normalize_to_standard_event

class WebRequestPayload(BaseModel):
    user_name: str
    user_email: str
    emergency_details: str
    browser_info: str = ""
    location: str = ""

class WebAdapter(BaseAdapter):
    def receive_and_normalize(self, raw_data: WebRequestPayload) -> StandardEmergencyEvent:
        """
        Normalizes a web form submission into a StandardEmergencyEvent.
        """
        return normalize_to_standard_event(
            source="web",
            message=raw_data.emergency_details,
            sender=f"{raw_data.user_name} <{raw_data.user_email}>",
            metadata={"browser_info": raw_data.browser_info, "location": raw_data.location}
        )

web_adapter_instance = WebAdapter()
