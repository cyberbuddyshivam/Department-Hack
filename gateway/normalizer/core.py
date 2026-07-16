from models.event import StandardEmergencyEvent
from typing import Dict, Any, List

def normalize_to_standard_event(
    source: str, 
    message: str, 
    sender: str, 
    attachments: List[str] = None, 
    metadata: Dict[str, Any] = None
) -> StandardEmergencyEvent:
    """
    Core function to normalize raw adapter data into the StandardEmergencyEvent.
    """
    return StandardEmergencyEvent(
        source=source,
        message=message,
        sender=sender,
        attachments=attachments or [],
        metadata=metadata or {}
    )
