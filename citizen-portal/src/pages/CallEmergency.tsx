import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Phone, PhoneOff, Loader2, ShieldAlert } from 'lucide-react';
import axios from 'axios';
const OPENROUTER_API_KEY = import.meta.env.VITE_OPENROUTER_API_KEY || "";

interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export default function CallEmergency() {
  const navigate = useNavigate();
  const [callState, setCallState] = useState<'idle' | 'calling' | 'connected' | 'processing'>('idle');
  const [callDuration, setCallDuration] = useState(0);
  const [transcript, setTranscript] = useState<string[]>([]);
  
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const recognitionRef = useRef<any>(null);
  const synthesisRef = useRef<SpeechSynthesisUtterance | null>(null);

  const conversationHistory = useRef<ChatMessage[]>([
    { role: 'system', content: `You are Aegis AI Emergency Voice Dispatcher. You are talking to a person in an emergency. 
Keep your responses VERY brief (1-2 sentences). 
Ask for their emergency and location. 
Once you have BOTH the emergency type and location, say exactly "DISPATCH_CONFIRMED:" followed by a short summary of the emergency and location. 
Do not use markdown. Speak naturally as a phone operator.` }
  ]);

  const speak = (text: string, onEnd?: () => void) => {
    const cleanText = text.replace('DISPATCH_CONFIRMED:', '').trim();
    setTranscript(prev => [...prev, `Aegis AI: ${cleanText}`]);
    
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(cleanText);
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      if (onEnd) utterance.onend = onEnd;
      synthesisRef.current = utterance;
      window.speechSynthesis.speak(utterance);
    } else if (onEnd) {
      setTimeout(onEnd, 2000);
    }
  };

  const listen = () => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Speech recognition is not supported in this browser. Please use text input instead.');
      return;
    }
    
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    
    recognition.onresult = (event: any) => {
      const userSpeech = event.results[0][0].transcript;
      setTranscript(prev => [...prev, `You: ${userSpeech}`]);
      handleUserSpeech(userSpeech);
    };
    
    recognition.onerror = (event: any) => {
      console.error('Speech recognition error', event.error);
      if (event.error !== 'no-speech' && callState === 'connected') {
         setTimeout(listen, 1000);
      }
    };

    recognition.start();
    recognitionRef.current = recognition;
  };

  const handleEndCallAndDispatch = async (summary: string) => {
    if (callState === 'processing') return;
    setCallState('processing');
    if (timerRef.current) clearInterval(timerRef.current);
    if (recognitionRef.current) recognitionRef.current.abort();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    
    try {
      const response = await axios.post('http://localhost:8000/adapters/web', {
        user_name: 'Voice Caller',
        user_email: 'voice@aegis.ai',
        emergency_details: summary,
        browser_info: navigator.userAgent,
        location: 'Voice Extracted'
      });
      
      const eventId = response.data.event_id || 'CALL-911';
      navigate(`/status/${eventId}`, { state: { userInput: summary } });
    } catch (error) {
      console.error("Failed to submit call data", error);
      setTimeout(() => {
        navigate(`/status/SIM-CALL-88`, { state: { userInput: summary } });
      }, 1500);
    }
  };

  const handleUserSpeech = async (text: string) => {
    conversationHistory.current.push({ role: 'user', content: text });
    
    try {
      const response = await axios.post('https://openrouter.ai/api/v1/chat/completions', {
        model: 'tencent/hy3:free',
        messages: conversationHistory.current,
      }, {
        headers: {
          'Authorization': `Bearer ${OPENROUTER_API_KEY}`,
          'Content-Type': 'application/json'
        }
      });
      
      const aiReply = response.data.choices[0].message.content;
      conversationHistory.current.push({ role: 'assistant', content: aiReply });
      
      if (aiReply.includes('DISPATCH_CONFIRMED:')) {
        const summary = aiReply.split('DISPATCH_CONFIRMED:')[1] || aiReply;
        speak(aiReply, () => handleEndCallAndDispatch(summary.trim()));
      } else {
        speak(aiReply, () => listen());
      }
    } catch (err) {
      console.error(err);
      // Fallback
      try {
         const fallbackResponse = await axios.post('https://openrouter.ai/api/v1/chat/completions', {
            model: 'cohere/north-mini-code:free',
            messages: conversationHistory.current,
          }, {
            headers: {
              'Authorization': `Bearer ${OPENROUTER_API_KEY}`,
              'Content-Type': 'application/json'
            }
          });
          const aiReply = fallbackResponse.data.choices[0].message.content;
          conversationHistory.current.push({ role: 'assistant', content: aiReply });
          
          if (aiReply.includes('DISPATCH_CONFIRMED:')) {
            const summary = aiReply.split('DISPATCH_CONFIRMED:')[1] || aiReply;
            speak(aiReply, () => handleEndCallAndDispatch(summary.trim()));
          } else {
            speak(aiReply, () => listen());
          }
      } catch {
          const hardFallback = "I'm having trouble connecting. Dispatching emergency services to your location now.";
          speak(hardFallback, () => handleEndCallAndDispatch(text));
      }
    }
  };

  useEffect(() => {
    if (callState === 'connected') {
      timerRef.current = setInterval(() => {
        setCallDuration(prev => prev + 1);
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callState]);

  const handleStartCall = () => {
    setCallState('calling');
    setTimeout(() => {
      setCallState('connected');
      const greeting = "Aegis AI Emergency Services. What is your location and emergency?";
      conversationHistory.current.push({ role: 'assistant', content: greeting });
      speak(greeting, () => listen());
    }, 2500); 
  };

  const handleManualEndCall = () => {
     if (callState === 'processing') return;
     const transcriptText = transcript.join('\n');
     handleEndCallAndDispatch(transcriptText || "Call ended manually.");
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const dialPad = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4 md:p-6 relative min-h-[calc(100vh-64px)]">
      <div className="absolute top-[10%] left-[10%] w-24 h-24 bg-[#cce3de] border-4 border-black rounded-sm rotate-12 z-0" />
      <div className="absolute bottom-[20%] right-[10%] w-32 h-32 bg-[#ffc2d1] border-4 border-black rounded-full z-0" />
      
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="neu-box p-6 md:p-10 max-w-md w-full z-10 bg-white shadow-[8px_8px_0px_black]"
      >
        <div className="text-center mb-8">
          <h2 className="text-3xl font-black mb-2 tracking-tight uppercase text-black">Aegis AI Voice</h2>
          <p className="text-black font-medium border-2 border-black inline-block px-3 py-1 bg-[#fdf0d5] shadow-[2px_2px_0px_black]">Intelligent Emergency Line</p>
        </div>
        
        <AnimatePresence mode="wait">
          {callState === 'idle' && (
            <motion.div 
              key="idle"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-6"
            >
              <div className="w-full text-center p-4 border-4 border-black bg-gray-100 text-3xl font-black tracking-widest shadow-inner">
                911 - AEGIS
              </div>
              
              <div className="grid grid-cols-3 gap-4 w-full">
                {dialPad.map((num) => (
                  <button key={num} className="neu-btn aspect-square text-2xl font-black flex items-center justify-center bg-white hover:bg-gray-200 shadow-[2px_2px_0px_black]">
                    {num}
                  </button>
                ))}
              </div>
              
              <button 
                onClick={handleStartCall}
                className="neu-btn w-full py-4 mt-4 bg-green-400 hover:bg-green-500 text-black flex items-center justify-center gap-3 text-xl shadow-[4px_4px_0px_black]"
              >
                <Phone className="w-6 h-6 fill-black" />
                CALL AI DISPATCH
              </button>
            </motion.div>
          )}

          {(callState === 'calling' || callState === 'connected' || callState === 'processing') && (
            <motion.div 
              key="calling"
              initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-8 py-8"
            >
              <div className="relative">
                <div className={`w-32 h-32 rounded-full border-4 border-black flex items-center justify-center shadow-[4px_4px_0px_black] ${callState === 'connected' ? 'bg-[#2dd4bf]' : 'bg-yellow-400'}`}>
                  <ShieldAlert className="w-16 h-16 text-black" />
                </div>
                {callState === 'connected' && (
                  <>
                    <motion.div 
                      animate={{ scale: [1, 1.2, 1] }} 
                      transition={{ repeat: Infinity, duration: 1.5 }}
                      className="absolute inset-0 rounded-full border-4 border-[#2dd4bf] opacity-50"
                    />
                    <motion.div 
                      animate={{ scale: [1, 1.5, 1] }} 
                      transition={{ repeat: Infinity, duration: 2 }}
                      className="absolute inset-0 rounded-full border-4 border-[#2dd4bf] opacity-20"
                    />
                  </>
                )}
              </div>
              
              <div className="text-center space-y-2">
                <h3 className="text-2xl font-black uppercase text-black">Aegis AI</h3>
                {callState === 'calling' && <p className="text-lg font-bold text-gray-500 animate-pulse">Dialing...</p>}
                {callState === 'connected' && <p className="text-2xl font-mono font-black text-black">{formatTime(callDuration)}</p>}
                {callState === 'processing' && (
                  <p className="text-lg font-bold text-blue-600 flex items-center justify-center gap-2">
                    <Loader2 className="w-5 h-5 animate-spin" /> Dispatching...
                  </p>
                )}
              </div>

              {callState === 'connected' && (
                <div className="w-full bg-gray-100 border-4 border-black p-4 h-40 overflow-y-auto flex flex-col gap-2 shadow-inner">
                  {transcript.map((text, idx) => (
                    <div key={idx} className={`p-2 border-2 border-black text-sm font-bold ${text.startsWith('You:') ? 'bg-white self-end' : 'bg-[#cce3de] self-start'}`}>
                      {text}
                    </div>
                  ))}
                </div>
              )}
              
              <button 
                onClick={handleManualEndCall}
                disabled={callState === 'processing'}
                className="neu-btn w-16 h-16 rounded-full bg-red-500 hover:bg-red-600 text-white flex items-center justify-center shadow-[4px_4px_0px_black] disabled:opacity-50 mt-4"
              >
                {callState === 'processing' ? <Loader2 className="w-6 h-6 animate-spin" /> : <PhoneOff className="w-8 h-8" />}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
        
      </motion.div>
    </div>
  );
}
