from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime
import uuid

class StandardEmergencyEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    message: str
    sender: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    attachments: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
