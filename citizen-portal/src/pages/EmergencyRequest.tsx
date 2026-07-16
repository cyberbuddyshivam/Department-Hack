import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Mic, Send, MapPin, Loader2, Square, AlertCircle, Edit3, Bot } from 'lucide-react';
import axios from 'axios';

export default function EmergencyRequest() {
  const navigate = useNavigate();
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [details, setDetails] = useState('');
  const [name, setName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [speechError, setSpeechError] = useState('');
  const [showTextFallback, setShowTextFallback] = useState(false);
  const [locationCoords, setLocationCoords] = useState('');
  const [isLocating, setIsLocating] = useState(false);
  
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioDataRef = useRef<Float32Array[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioContextRef.current = audioContext;
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      
      processor.onaudioprocess = (e) => {
        const channelData = e.inputBuffer.getChannelData(0);
        audioDataRef.current.push(new Float32Array(channelData));
      };
      
      source.connect(processor);
      processor.connect(audioContext.destination);
      processorRef.current = processor;
      
      audioDataRef.current = [];
      setIsRecording(true);
      setSpeechError('');
      setShowTextFallback(true);
      setDetails(''); 
    } catch (err) {
      console.error("Microphone permission denied", err);
      setSpeechError("Microphone access denied. Please use text instead.");
      setShowTextFallback(true);
    }
  };

  const exportWAV = (audioData: Float32Array[], sampleRate: number) => {
    const bufferLength = audioData.length * 4096;
    const buffer = new Float32Array(bufferLength);
    let offset = 0;
    for (let i = 0; i < audioData.length; i++) {
      buffer.set(audioData[i], offset);
      offset += audioData[i].length;
    }
    
    const data = new Int16Array(bufferLength);
    for (let i = 0; i < bufferLength; i++) {
      let s = Math.max(-1, Math.min(1, buffer[i]));
      data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    const wavBuffer = new ArrayBuffer(44 + data.length * 2);
    const view = new DataView(wavBuffer);
    const writeString = (view: DataView, offset: number, string: string) => {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    };
    
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + data.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); 
    view.setUint16(22, 1, true); 
    view.setUint32(24, sampleRate, true); 
    view.setUint32(28, sampleRate * 2, true); 
    view.setUint16(32, 2, true); 
    view.setUint16(34, 16, true); 
    writeString(view, 36, 'data');
    view.setUint32(40, data.length * 2, true);
    
    let index = 44;
    for (let i = 0; i < data.length; i++) {
      view.setInt16(index, data[i], true);
      index += 2;
    }
    
    return new Blob([view], { type: 'audio/wav' });
  };

  const stopRecordingAndTranscribe = async () => {
    if (!processorRef.current || !audioContextRef.current) return;
    
    processorRef.current.disconnect();
    processorRef.current = null;
    
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    
    setIsRecording(false);
    setIsTranscribing(true);
    setDetails('Sarvam AI is processing and translating your voice...');
    
    const sampleRate = audioContextRef.current.sampleRate;
    const audioBlob = exportWAV(audioDataRef.current, sampleRate);
    
    const formData = new FormData();
    formData.append('file', audioBlob, 'emergency.wav');
    
    try {
      const response = await axios.post('http://localhost:8000/adapters/web/transcribe', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      const { transcript, sentiment } = response.data;
      setDetails(`${transcript}\n\n[AI Decoding: ${sentiment}]`);
    } catch (err) {
      console.error(err);
      setSpeechError("Translation AI failed to process audio.");
      setDetails('');
    } finally {
      setIsTranscribing(false);
    }
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecordingAndTranscribe();
    } else {
      startRecording();
    }
  };

  const handleGetLocation = () => {
    setIsLocating(true);
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser");
      setIsLocating(false);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocationCoords(`${position.coords.latitude.toFixed(4)}, ${position.coords.longitude.toFixed(4)}`);
        setIsLocating(false);
      },
      (error) => {
        console.error("Error getting location", error);
        alert("Failed to get location. Please enable location permissions in your browser.");
        setIsLocating(false);
      }
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!details.trim() || isTranscribing) return;
    
    if (isRecording) {
      stopRecordingAndTranscribe(); // Force stop if they hit submit while recording
      return; 
    }
    
    setIsSubmitting(true);
    try {
      const finalDetails = locationCoords ? `${details}\n[Location Coordinates: ${locationCoords}]` : details;
      
      const response = await axios.post('http://localhost:8000/adapters/web', {
        user_name: name || 'Anonymous Citizen',
        user_email: 'unknown@web.portal',
        emergency_details: finalDetails,
        browser_info: navigator.userAgent,
        location: locationCoords
      });
      
      const eventId = response.data.event_id || 'REQ-911';
      navigate(`/status/${eventId}`, { state: { userInput: finalDetails } });
    } catch (error) {
      console.error("Failed to submit", error);
      alert("Failed to submit emergency request. Ensure backend is running.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4 md:p-6 relative min-h-[calc(100vh-64px)]">
      {/* Neubrutalism background shapes */}
      <div className="absolute top-[10%] right-[10%] w-24 h-24 bg-[#ff477e] border-4 border-black rounded-sm rotate-45 z-0" />
      <div className="absolute bottom-[20%] left-[10%] w-32 h-32 bg-[#2dd4bf] border-4 border-black rounded-full z-0" />
      
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="neu-box p-6 md:p-10 max-w-2xl w-full z-10 bg-white"
      >
        <div className="text-center mb-8">
          <h2 className="text-3xl md:text-5xl font-black mb-3 tracking-tight uppercase text-black">Report Emergency</h2>
          <p className="text-black font-medium border-2 border-black inline-block p-2 bg-[#f4f4f0] shadow-[2px_2px_0px_black]">Speak in any language. Sarvam AI will translate and analyze it.</p>
        </div>
        
        <form onSubmit={handleSubmit} className="space-y-8">
          
          {/* Main Voice Input Section */}
          <div className="flex flex-col items-center justify-center py-6">
            <button
              type="button"
              onClick={toggleRecording}
              disabled={isTranscribing}
              className={`relative flex items-center justify-center w-32 h-32 rounded-full cursor-pointer transition-all duration-300 border-4 border-black shadow-[6px_6px_0px_black] ${
                isRecording 
                  ? 'bg-primary translate-y-[2px] translate-x-[2px] shadow-[4px_4px_0px_black]' 
                  : isTranscribing
                  ? 'bg-[#2dd4bf] animate-pulse'
                  : 'bg-white hover:bg-gray-100 hover:translate-y-[2px] hover:translate-x-[2px] hover:shadow-[4px_4px_0px_black]'
              }`}
            >
              {isRecording ? (
                <Square className="w-12 h-12 text-black" />
              ) : isTranscribing ? (
                <Bot className="w-12 h-12 text-black" />
              ) : (
                <Mic className="w-12 h-12 text-black" />
              )}
            </button>
            <p className="mt-6 text-sm font-black text-black uppercase tracking-widest bg-[#fdf274] border-2 border-black px-3 py-1 shadow-[2px_2px_0px_black]">
              {isRecording ? 'Listening... Tap to Stop' : isTranscribing ? 'Translating via Sarvam...' : 'Tap to Speak'}
            </p>
          </div>

          <AnimatePresence>
            {speechError && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-primary text-sm justify-center">
                <AlertCircle className="w-4 h-4" /> {speechError}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-sm font-black uppercase text-black ml-1">Emergency Transcript & Sentiment</label>
              {!showTextFallback && (
                <button 
                  type="button" 
                  onClick={() => setShowTextFallback(true)}
                  className="text-xs font-bold text-black hover:bg-gray-200 border-2 border-black px-2 py-1 flex items-center gap-1 cursor-pointer transition-colors shadow-[2px_2px_0px_black]"
                >
                  <Edit3 className="w-3 h-3" /> Type Manually instead
                </button>
              )}
            </div>
            
            {showTextFallback || details || isRecording ? (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <textarea 
                  required
                  value={details}
                  onChange={(e) => setDetails(e.target.value)}
                  disabled={isTranscribing}
                  rows={5}
                  className={`neu-input w-full px-5 py-4 resize-none ${
                    isRecording 
                      ? 'bg-[#ffc2d1]' 
                      : isTranscribing
                      ? 'bg-[#ccfbf1]'
                      : 'bg-white'
                  }`}
                  placeholder={isRecording ? "Recording your emergency... Speak freely in any language." : "Describe the emergency..."}
                />
              </motion.div>
            ) : null}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-black uppercase text-black ml-1">Your Name (Optional)</label>
              <input 
                type="text" 
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={isTranscribing}
                className="neu-input w-full px-4 py-3 bg-white disabled:opacity-50"
                placeholder="John Doe"
              />
            </div>
            <div className="flex items-end h-full">
               <button 
                 type="button" 
                 onClick={handleGetLocation}
                 disabled={isLocating || !!locationCoords || isTranscribing}
                 className={`neu-btn w-full h-[50px] flex items-center justify-center gap-2 ${
                   locationCoords 
                     ? 'bg-[#2dd4bf] text-black' 
                     : 'bg-[#f4f4f0] text-black'
                 }`}
               >
                {isLocating ? (
                  <><Loader2 className="w-5 h-5 animate-spin" /> Locating...</>
                ) : locationCoords ? (
                  <><MapPin className="w-5 h-5" /> {locationCoords}</>
                ) : (
                  <><MapPin className="w-5 h-5" /> Share Location</>
                )}
              </button>
            </div>
          </div>

          <button 
            type="submit" 
            disabled={isSubmitting || !details.trim() || isTranscribing || isRecording}
            className="neu-btn w-full py-4 flex items-center justify-center gap-3 text-lg cursor-pointer disabled:opacity-50 mt-4 bg-[#ff477e] text-white hover:bg-[#e03566]"
          >
            {isSubmitting ? (
              <Loader2 className="w-6 h-6 animate-spin" />
            ) : (
              <>
                <Send className="w-6 h-6" /> DISPATCH AI EMERGENCY
              </>
            )}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
