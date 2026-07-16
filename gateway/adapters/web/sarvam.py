import requests
import logging

logger = logging.getLogger(__name__)
SARVAM_API_KEY = "sk_grf8jssu_nYAo7ssiXltP9lkBZ9sqkfai"

def transcribe_and_translate(audio_file_path: str) -> str:
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": SARVAM_API_KEY}
    with open(audio_file_path, "rb") as f:
        files = {"file": ("emergency.wav", f, "audio/wav")}
        data = {"prompt": "emergency medical context"}
        try:
            response = requests.post(url, headers=headers, files=files, data=data)
            if response.status_code == 200:
                return response.json().get("transcript", "")
            else:
                logger.error(f"Sarvam STT Error: {response.text}")
                return f"ERROR_STT: {response.status_code} {response.text}"
        except Exception as e:
            logger.error(f"Sarvam API Exception: {e}")
            return f"ERROR_EX: {str(e)}"

def analyze_sentiment(transcript: str) -> str:
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sarvam-30b", # Sarvam's fast model for quick chat completion
        "messages": [
            {"role": "system", "content": "You are an expert AI triage system. Read the user's transcript. Output exactly one line detailing the emotional sentiment and the core medical intent. Example: 'Sentiment: Panic | Intent: Chest Pain' or 'Sentiment: Calm | Intent: Requesting checkup'."},
            {"role": "user", "content": transcript}
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Sarvam LLM Error: {response.text}")
            return "Unable to decode sentiment"
    except Exception as e:
        logger.error(f"Sarvam LLM Exception: {e}")
        return "Unable to decode sentiment"

def generate_dispatcher_response(user_input: str) -> str:
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sarvam-30b",
        "messages": [
            {"role": "system", "content": "You are an autonomous AI 911 medical dispatcher. Keep your response under 2 short sentences. Be reassuring, decisive, and state that an ambulance or help is being evaluated. Ask one short follow-up question if needed (e.g. 'Are you in a safe place?')."},
            {"role": "user", "content": user_input}
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Sarvam Conversational LLM Error: {response.text}")
            return "I am dispatching an ambulance to your location immediately. Please stay safe."
    except Exception as e:
        logger.error(f"Sarvam API Exception: {e}")
        return "Help is on the way. Please stay calm."
