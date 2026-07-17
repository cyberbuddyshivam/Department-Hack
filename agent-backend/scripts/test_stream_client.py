import httpx
import json

def test_stream():
    payload = {
        "incident_id": "test-stream-2",
        "input_sources": {"text": "Severe chest pain, likely heart attack."},
        "caller_location": {"lat": 19.1172, "lng": 72.8340}
    }
    
    print("--- STARTING STREAM ---")
    with httpx.stream("POST", "http://localhost:8000/incident/stream", json=payload, timeout=30.0) as r:
        for chunk in r.iter_text():
            print(chunk, end="", flush=True)
    print("--- STREAM COMPLETE ---")

if __name__ == "__main__":
    test_stream()
