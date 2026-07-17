from fastapi import FastAPI, HTTPException, Form, File, UploadFile, BackgroundTasks
import tempfile
import os
from fastapi.middleware.cors import CORSMiddleware
from models.event import StandardEmergencyEvent
from dispatcher.agent_api import dispatcher, TRACKING_RESULTS
from adapters.web.adapter import WebRequestPayload, web_adapter_instance
import utils.logger

# Initialize logger
utils.logger.setup_logger()

app = FastAPI(
    title="Multi-Channel Emergency Gateway",
    description="Single entry point for all emergency requests, standardizing and forwarding to the AI Multi-Agent System.",
    version="1.0.0"
)

# Allow CORS for Citizen Portal
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for hackathon, adjust to ["http://localhost:5173"] for strict
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/tracking/{event_id}", tags=["Core"])
async def get_tracking_data(event_id: str):
    """
    Returns the final output produced by the multi-agent system for a given incident.
    """
    if event_id not in TRACKING_RESULTS:
        return {"status": "processing", "agent_trace": [], "map_data": None}
    return TRACKING_RESULTS[event_id]

@app.post("/emergency", response_model=dict, tags=["Core"])
async def receive_standard_emergency(event: StandardEmergencyEvent, background_tasks: BackgroundTasks):
    """
    The single endpoint where ALL adapters eventually send their normalized data.
    It forwards the StandardEmergencyEvent to the downstream multi-agent system.
    """
    background_tasks.add_task(dispatcher.dispatch, event)
    return {"status": "success", "message": "Event dispatched to multi-agent system", "event_id": event.id}

@app.post("/adapters/web", tags=["Adapters"])
async def handle_web_request(payload: WebRequestPayload, background_tasks: BackgroundTasks):
    """
    Phase 2: Web Adapter Endpoint.
    Receives raw web request, normalizes it, and sends to the standard /emergency pipeline.
    """
    standard_event = web_adapter_instance.receive_and_normalize(payload)
    
    # Forward to the central endpoint logic
    background_tasks.add_task(dispatcher.dispatch, standard_event)
        
    return {"status": "success", "event_id": standard_event.id}

@app.post("/adapters/web/transcribe", tags=["Adapters"])
async def handle_transcription(file: UploadFile = File(...)):
    """
    Phase 7: Web Voice Transcriber.
    Takes a raw audio file from the web frontend, sends it to Sarvam AI for translation,
    extracts sentiment, and returns it to the frontend for the user to review.
    """
    from adapters.web.sarvam import transcribe_and_translate, analyze_sentiment
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
        temp_audio.write(await file.read())
        temp_audio_path = temp_audio.name
        
    transcript = transcribe_and_translate(temp_audio_path)
    os.remove(temp_audio_path)
    
    if not transcript or transcript.startswith("ERROR_"):
        return {"transcript": f"Failed to transcribe audio. Reason: {transcript}", "sentiment": "Unknown"}
        
    sentiment = analyze_sentiment(transcript)
    return {"transcript": transcript, "sentiment": sentiment}

@app.post("/adapters/sms", tags=["Adapters"])
async def handle_sms_request(
    From: str = Form(...),
    Body: str = Form(...),
    MediaUrl0: str = Form(None)
):
    """
    Phase 4: SMS Adapter Endpoint.
    Receives incoming form-encoded data from Twilio Webhooks, normalizes it, and dispatches.
    """
    from adapters.sms.adapter import TwilioSmsPayload, sms_adapter_instance
    
    payload = TwilioSmsPayload(From=From, Body=Body, MediaUrl0=MediaUrl0)
    standard_event = sms_adapter_instance.receive_and_normalize(payload)
    
    success = dispatcher.dispatch(standard_event)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to dispatch to agent system")
        
    # Twilio expects an XML response, even an empty one is fine for no reply
    from fastapi import Response
    return Response(content="<Response></Response>", media_type="application/xml")

@app.post("/adapters/voice", tags=["Adapters"])
async def handle_incoming_call():
    """
    Phase 5: Voice Adapter Initial Endpoint.
    Initiates an interactive AI conversational loop over the phone using Twilio Gather.
    """
    from twilio.twiml.voice_response import VoiceResponse, Gather
    response = VoiceResponse()
    gather = Gather(input="speech", action="/adapters/voice/record", speechTimeout="auto")
    gather.say("You have reached the Autonomous A.I. Emergency Dispatch. Please clearly state your emergency.", voice="alice")
    response.append(gather)
    # Fallback if they don't speak
    response.say("We did not hear anything. Goodbye.", voice="alice")
    
    from fastapi import Response
    return Response(content=str(response), media_type="application/xml")

@app.post("/adapters/voice/record", tags=["Adapters"])
async def handle_voice_recording(
    From: str = Form(...),
    CallSid: str = Form(...),
    RecordingUrl: str = Form(None),
    TranscriptionText: str = Form(None),
    SpeechResult: str = Form(None)
):
    """
    Phase 5: Conversational AI Loop
    Receives the speech result, generates AI reply, and dispatches the event.
    """
    # 1. Generate Conversational AI Response via Sarvam
    from adapters.web.sarvam import generate_dispatcher_response
    user_speech = SpeechResult or TranscriptionText or "I need help."
    ai_reply = generate_dispatcher_response(user_speech)
    
    # 2. Dispatch to the teammate's AI system
    from adapters.voice.adapter import TwilioVoicePayload, voice_adapter_instance
    payload = TwilioVoicePayload(
        From=From, 
        CallSid=CallSid, 
        RecordingUrl=RecordingUrl, 
        TranscriptionText=TranscriptionText,
        SpeechResult=SpeechResult
    )
    standard_event = voice_adapter_instance.receive_and_normalize(payload)
    dispatcher.dispatch(standard_event)
    
    # 3. Speak the AI reply back to the caller
    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say(ai_reply, voice="alice")
    
    from fastapi import Response
    return Response(content=str(response), media_type="application/xml")

@app.post("/adapters/whatsapp", tags=["Adapters"])
async def handle_whatsapp_request(
    From: str = Form(...),
    Body: str = Form(...),
    MediaUrl0: str = Form(None),
    ProfileName: str = Form(None)
):
    """
    Phase 6: WhatsApp Adapter Endpoint.
    Receives incoming WhatsApp messages from Twilio, normalizes, and dispatches.
    """
    from adapters.whatsapp.adapter import WhatsAppPayload, whatsapp_adapter_instance
    
    payload = WhatsAppPayload(From=From, Body=Body, MediaUrl0=MediaUrl0, ProfileName=ProfileName)
    standard_event = whatsapp_adapter_instance.receive_and_normalize(payload)
    
    success = dispatcher.dispatch(standard_event)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to dispatch to agent system")
        
    from fastapi import Response
    return Response(content="<Response></Response>", media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    from config.settings import settings
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
