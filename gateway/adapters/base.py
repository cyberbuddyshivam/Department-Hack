from abc import ABC, abstractmethod
from models.event import StandardEmergencyEvent

class BaseAdapter(ABC):
    @abstractmethod
    def receive_and_normalize(self, raw_data: any) -> StandardEmergencyEvent:
        """
        Every adapter must implement this to convert raw data to StandardEmergencyEvent.
        """
        pass
