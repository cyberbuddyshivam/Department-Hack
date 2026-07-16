from pydantic import BaseModel
from typing import Optional
from adapters.base import BaseAdapter
from models.event import StandardEmergencyEvent
from normalizer.core import normalize_to_standard_event

class WhatsAppPayload(BaseModel):
    From: str
    Body: str
    MediaUrl0: Optional[str] = None
    ProfileName: Optional[str] = None

class WhatsAppAdapter(BaseAdapter):
    def receive_and_normalize(self, raw_data: WhatsAppPayload) -> StandardEmergencyEvent:
        """
        Normalizes an incoming WhatsApp message via Twilio into a StandardEmergencyEvent.
        """
        attachments = []
        if raw_data.MediaUrl0:
            attachments.append(raw_data.MediaUrl0)
            
        # Clean the "whatsapp:" prefix Twilio usually adds
        sender = raw_data.From.replace("whatsapp:", "")
        if raw_data.ProfileName:
            sender = f"{raw_data.ProfileName} ({sender})"
            
        return normalize_to_standard_event(
            source="whatsapp",
            message=raw_data.Body,
            sender=sender,
            attachments=attachments,
            metadata={"provider": "twilio_whatsapp"}
        )

whatsapp_adapter_instance = WhatsAppAdapter()
