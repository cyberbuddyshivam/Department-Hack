import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Truck, Stethoscope, MessageSquare, Clock } from 'lucide-react';
import { MapContainer, TileLayer, Marker, Polyline, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix Leaflet's default icon issue
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Custom neubrutalism icons
const hospitalIcon = new L.DivIcon({
  html: `<div class="w-10 h-10 bg-white border-4 border-black flex items-center justify-center font-bold text-lg shadow-[4px_4px_0px_black] rounded-full">H</div>`,
  className: '',
  iconSize: [40, 40],
  iconAnchor: [20, 20],
});

const patientIcon = new L.DivIcon({
  html: `<div class="w-10 h-10 bg-[#2dd4bf] border-4 border-black rounded-full flex items-center justify-center shadow-[4px_4px_0px_black]">P</div>`,
  className: '',
  iconSize: [40, 40],
  iconAnchor: [20, 20],
});

const ambulanceIcon = new L.DivIcon({
  html: `<div class="w-10 h-10 bg-white border-4 border-black shadow-[4px_4px_0px_black] flex items-center justify-center rounded-sm"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ff477e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-truck"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11h1"/><path d="M15 18H9"/><path d="M19 18h2a2 2 0 0 0 2-2v-3.6c0-1.2-.5-2.3-1.4-3.1L19 7h-5v11h1"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/></svg></div>`,
  className: '',
  iconSize: [40, 40],
  iconAnchor: [20, 20],
});

const HOSPITAL_POS: [number, number] = [34.0622, -118.2537];
const PATIENT_POS: [number, number] = [34.0522, -118.2437];

interface ChatMessage {
  sender: 'Agent' | 'User';
  text: string;
}

export default function AmbulanceTracking() {
  const { id } = useParams();
  const [timeLeft, setTimeLeft] = useState(320); // 5 mins 20 secs in seconds
  const [ambulancePos, setAmbulancePos] = useState<[number, number]>(HOSPITAL_POS);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { sender: 'Agent', text: 'Hello, I am your Medical AI Assistant. The ambulance is on the way.' },
    { sender: 'Agent', text: 'Please ensure the patient is laying flat. Are they conscious and breathing regularly?' }
  ]);
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    const totalTime = 320;
    const timer = setInterval(() => {
      setTimeLeft(prev => {
        const nextTime = prev > 0 ? prev - 1 : 0;
        
        // Calculate ambulance position based on time left
        const progress = 1 - (nextTime / totalTime); // 0 to 1
        const lat = HOSPITAL_POS[0] + (PATIENT_POS[0] - HOSPITAL_POS[0]) * progress;
        const lng = HOSPITAL_POS[1] + (PATIENT_POS[1] - HOSPITAL_POS[1]) * progress;
        setAmbulancePos([lat, lng]);
        
        return nextTime;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;

    // Add user message
    setMessages(prev => [...prev, { sender: 'User', text: inputText }]);
    const userInput = inputText;
    setInputText('');

    // Simulate Agent response based on user input
    setTimeout(() => {
      let reply = 'Understood. Please keep monitoring their vitals and stay calm.';
      const lower = userInput.toLowerCase();
      if (lower.includes('not breathing') || lower.includes('no')) {
        reply = 'URGENT: Begin CPR immediately. Place your hands on the center of their chest and push hard and fast. The ambulance is prioritizing this call.';
      } else if (lower.includes('yes') || lower.includes('breathing')) {
        reply = 'Good. Keep them comfortable. Do not give them anything to eat or drink. Monitor their pulse.';
      } else if (lower.includes('bleeding')) {
        reply = 'Apply firm, direct pressure to the wound using a clean cloth. Do not remove it if it gets soaked, add another layer.';
      }
      setMessages(prev => [...prev, { sender: 'Agent', text: reply }]);
    }, 1500);
  };

  return (
    <div className="flex-1 flex flex-col p-4 md:p-8 max-w-4xl mx-auto w-full gap-6">
      
      {/* Header */}
      <div className="flex items-center justify-between neu-box p-4 bg-[#fdf274]">
        <h1 className="text-2xl font-black uppercase flex items-center gap-2">
          <Truck className="w-8 h-8 text-primary" />
          Live Ambulance Tracking
        </h1>
        <div className="font-bold border-2 border-black px-3 py-1 bg-white">ID: {id || 'SIM-8842'}</div>
      </div>

      {/* Map Section */}
      <div className="neu-box p-0 overflow-hidden bg-[#e2ece9] relative h-96 flex flex-col border-4 border-black shadow-[6px_6px_0px_black] z-0">
        <div className="bg-black text-white px-3 py-2 font-black uppercase text-sm z-10 border-b-4 border-black inline-block self-start absolute top-0 left-0">
          Live Map Tracking
        </div>
        
        <div className="flex-1 w-full h-full relative z-0">
          <MapContainer center={[34.0572, -118.2487]} zoom={14} className="w-full h-full z-0" zoomControl={false}>
            <TileLayer
              attribution='&copy; <a href="https://osm.org/copyright">OpenStreetMap</a>'
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            />
            <Marker position={HOSPITAL_POS} icon={hospitalIcon}>
              <Popup>Mercy Med Hospital</Popup>
            </Marker>
            <Marker position={PATIENT_POS} icon={patientIcon}>
              <Popup>Patient Location</Popup>
            </Marker>
            <Polyline positions={[HOSPITAL_POS, PATIENT_POS]} pathOptions={{ color: 'black', weight: 6, dashArray: '10, 10' }} />
            <Marker position={ambulancePos} icon={ambulanceIcon} zIndexOffset={1000} />
          </MapContainer>
        </div>
      </div>

      {/* Time Remaining Section */}
      <div className="neu-box p-6 bg-white flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="bg-[#2dd4bf] p-3 border-4 border-black shadow-[4px_4px_0px_black]">
            <Clock className="w-8 h-8 text-black animate-pulse" />
          </div>
          <div>
            <h2 className="text-xl font-black uppercase">Estimated Arrival</h2>
            <p className="font-bold text-gray-500">Ambulance is en route</p>
          </div>
        </div>
        <div className="text-5xl font-black text-[#ff477e] drop-shadow-[2px_2px_0px_black]">
          {formatTime(timeLeft)}
        </div>
      </div>

      {/* Medical Guide Chatbot Section */}
      <div className="neu-box bg-[#fcd5ce] flex flex-col flex-1 h-[450px] overflow-hidden">
        <div className="bg-black text-white px-4 py-3 font-black uppercase text-sm border-b-4 border-black flex items-center justify-between">
          <span className="flex items-center gap-2"><Stethoscope className="w-5 h-5" /> Agent 5: Medical Guide</span>
          <span className="bg-red-500 text-white px-2 py-0.5 text-xs animate-pulse">ACTIVE</span>
        </div>
        
        <div className="p-4 flex-1 flex flex-col gap-4 overflow-y-auto bg-[#fff0ed]">
          <AnimatePresence>
            {messages.map((msg, idx) => {
              const isUser = msg.sender === 'User';
              return (
                <motion.div 
                  key={idx}
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  className={`border-4 border-black p-4 shadow-[4px_4px_0px_black] max-w-[85%] ${
                    isUser 
                      ? 'bg-[#ffc2d1] self-end rounded-bl-2xl rounded-tr-2xl rounded-tl-2xl rounded-br-sm' 
                      : 'bg-white self-start rounded-br-2xl rounded-tr-2xl rounded-tl-sm rounded-bl-2xl'
                  }`}
                >
                  <p className="font-black text-xs uppercase mb-1 border-b-2 border-black inline-block">{msg.sender}</p>
                  <p className="font-bold text-sm text-black">{msg.text}</p>
                </motion.div>
              );
            })}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>
        
        {/* Chatbot input field */}
        <form onSubmit={handleSendMessage} className="p-4 border-t-4 border-black bg-white flex gap-2">
          <input 
            type="text" 
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="Reply to the Medical Guide..."
            className="neu-input flex-1 px-4 py-3 font-bold"
          />
          <button type="submit" className="neu-btn px-6 py-3 bg-primary text-black">
            <MessageSquare className="w-6 h-6" />
          </button>
        </form>
      </div>

    </div>
  );
}
