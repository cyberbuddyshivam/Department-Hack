from pydantic import BaseModel
from typing import Optional
from adapters.base import BaseAdapter
from models.event import StandardEmergencyEvent
from normalizer.core import normalize_to_standard_event

class TwilioVoicePayload(BaseModel):
    From: str
    RecordingUrl: Optional[str] = None
    TranscriptionText: Optional[str] = None
    SpeechResult: Optional[str] = None
    CallSid: str

class VoiceAdapter(BaseAdapter):
    def receive_and_normalize(self, raw_data: TwilioVoicePayload) -> StandardEmergencyEvent:
        """
        Normalizes a Twilio Voice call (recording & transcription) into a StandardEmergencyEvent.
        """
        attachments = []
        if raw_data.RecordingUrl:
            attachments.append(raw_data.RecordingUrl)
            
        return normalize_to_standard_event(
            source="voice",
            message=raw_data.SpeechResult or raw_data.TranscriptionText or "[No Speech Captured]",
            sender=raw_data.From,
            attachments=attachments,
            metadata={"provider": "twilio", "call_sid": raw_data.CallSid}
        )

voice_adapter_instance = VoiceAdapter()
