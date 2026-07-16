# Multi-Channel Emergency Gateway

This gateway serves as the single entry point for all emergency requests entering the Multi-Agent AI System.

## Architecture

1. **Adapters:** Receive requests from various channels (Voice, SMS, Email, Web, etc.).
2. **Normalizer:** Converts channel-specific payloads into a single `StandardEmergencyEvent`.
3. **Dispatcher:** Forwards the standardized event to the downstream multi-agent system.
4. **Endpoint:** `POST /emergency` serves as the final unified intake.

## Phases Implemented
- **Phase 1**: Base structure, Models, Normalizer, and Dispatcher.
- **Phase 2**: Web Adapter endpoint (`POST /adapters/web`).

## How to Run

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

## Next Steps
Future phases will implement remaining adapters (Voice, SMS, Email, WhatsApp) within the `adapters/` directory following the BaseAdapter interface.
