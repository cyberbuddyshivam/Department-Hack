import os

class Settings:
    AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8001/agent-flow")
    PORT = int(os.getenv("PORT", 8000))

settings = Settings()
