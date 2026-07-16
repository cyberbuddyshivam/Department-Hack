from pydantic import BaseModel
from typing import Optional
from adapters.base import BaseAdapter
from models.event import StandardEmergencyEvent
from normalizer.core import normalize_to_standard_event

class TwilioSmsPayload(BaseModel):
    From: str
    Body: str
    MediaUrl0: Optional[str] = None

class SmsAdapter(BaseAdapter):
    def receive_and_normalize(self, raw_data: TwilioSmsPayload) -> StandardEmergencyEvent:
        """
        Normalizes an incoming Twilio SMS payload into a StandardEmergencyEvent.
        """
        attachments = []
        if raw_data.MediaUrl0:
            attachments.append(raw_data.MediaUrl0)
            
        return normalize_to_standard_event(
            source="sms",
            message=raw_data.Body,
            sender=raw_data.From,
            attachments=attachments,
            metadata={"provider": "twilio"}
        )

sms_adapter_instance = SmsAdapter()
