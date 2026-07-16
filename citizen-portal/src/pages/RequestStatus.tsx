import { useState, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, Activity, ArrowRight, BrainCircuit, MapPin, Truck, Stethoscope, MessageSquare, Loader2, Navigation, ShieldAlert } from 'lucide-react';

interface LogEntry {
  sender: string;
  receiver: string;
  message: string;
  color: string;
}

export default function RequestStatus() {
  const { id } = useParams();
  const [step, setStep] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    const simulationSequence = async () => {
      // User Input Phase
      addLog('User', 'Agent 1', 'EMERGENCY: "My father collapsed, he is not breathing properly." Location: [34.05, -118.24]', 'bg-white');
      
      await delay(2000);
      setStep(1); // Agent 1 Processing
      await delay(3000);
      addLog('Agent 1', 'Agent 2', 'Identified 3 nearby facilities: City Gen (2km), Mercy Med (3km), Care Point (3.5km).', 'bg-[#fdf0d5]');
      
      setStep(2); // Agent 2 Processing
      await delay(3000);
      addLog('Agent 2', 'Agent 3', 'Traffic heavy on I-5. Mercy Med route clear. ETA: 6 mins. Selected Mercy Med.', 'bg-[#ffc2d1]');
      
      setStep(3); // Agent 3 Processing
      await delay(2000);
      addLog('Agent 3', 'Mercy Med', 'CRITICAL ALERT: Incoming trauma patient. Requesting immediate bed.', 'bg-[#ccfbf1]');
      await delay(2000);
      addLog('Mercy Med', 'Agent 3', 'Bed confirmed. Trauma team on standby.', 'bg-white');
      
      setStep(4); // Agent 4 Processing
      await delay(2000);
      addLog('Agent 3', 'Agent 4', 'Ambulance dispatched. Initiate live surveillance and tracking.', 'bg-[#e2ece9]');
      
      setStep(5); // Agent 5 Processing
      await delay(2000);
      addLog('Agent 4', 'Agent 5', 'Ambulance is en route. Connect to patient for medical guidance.', 'bg-[#e2ece9]');
      await delay(2000);
      addLog('Agent 5', 'User', 'Hello, I am your Medical Guide. The ambulance is 5 mins away. Please keep the patient flat and check breathing.', 'bg-[#fcd5ce]');
      setStep(6); // All Done
    };

    simulationSequence();
  }, []);

  const delay = (ms: number) => new Promise(res => setTimeout(res, ms));

  const addLog = (sender: string, receiver: string, message: string, color: string) => {
    setLogs(prev => [...prev, { sender, receiver, message, color }]);
  };

  const agents = [
    { id: 1, name: "Hospital Locator", icon: MapPin, color: "bg-[#fdf0d5]", task: "Find nearest hospitals", output: "Found: City Gen, Mercy Med, Care Point." },
    { id: 2, name: "Traffic Analyzer", icon: Navigation, color: "bg-[#ffc2d1]", task: "Check traffic & find fastest route", output: "Selected: Mercy Med (Fastest ETA 6m)." },
    { id: 3, name: "Hospital Coordinator", icon: ShieldAlert, color: "bg-[#ccfbf1]", task: "Alert facility & book bed", output: "Bed confirmed at Mercy Med." },
    { id: 4, name: "Surveillance", icon: Truck, color: "bg-[#e2ece9]", task: "Track ambulance route", output: "Ambulance dispatched & tracked." },
    { id: 5, name: "Medical Guide", icon: Stethoscope, color: "bg-[#fcd5ce]", task: "Provide interim guidance", output: "Assisting patient on site." }
  ];

  return (
    <div className="flex-1 flex flex-col p-4 md:p-8 max-w-6xl mx-auto w-full gap-6">
      
      {/* Header */}
      <div className="flex items-center justify-between neu-box p-4 bg-[#fdf274]">
        <h1 className="text-2xl font-black uppercase flex items-center gap-2">
          <Activity className="w-8 h-8 animate-pulse text-primary" />
          Multi-Agent Dispatch Active
        </h1>
        <div className="font-bold border-2 border-black px-3 py-1 bg-white">ID: {id || 'SIM-8842'}</div>
      </div>

      {/* User Input Section */}
      <div className="neu-box p-4 bg-white">
        <div className="bg-black text-white px-3 py-1 font-black uppercase text-sm border-b-4 border-black inline-block mb-2">
          Initial User Input
        </div>
        <p className="font-bold text-lg p-3 bg-gray-100 border-2 border-black shadow-[2px_2px_0px_black]">
          "My father collapsed, he is not breathing properly." <br/>
          <span className="text-sm font-medium text-gray-600">Location: Lat 34.0522, Lng -118.2437</span>
        </p>
      </div>

      {/* Agent Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {agents.map((agent) => {
          const isPending = step < agent.id;
          const isProcessing = step === agent.id;
          const isCompleted = step > agent.id;
          const Icon = agent.icon;

          return (
            <div 
              key={agent.id} 
              className={`neu-box flex flex-col overflow-hidden transition-opacity duration-500 ${isPending ? 'opacity-40 grayscale' : 'opacity-100'}`}
            >
              <div className={`p-3 border-b-4 border-black flex items-center justify-between ${agent.color}`}>
                <span className="font-black text-sm uppercase truncate pr-2">{agent.name}</span>
                <Icon className="w-5 h-5 flex-shrink-0" />
              </div>
              <div className="p-3 flex-1 flex flex-col bg-white">
                <p className="font-bold text-xs text-gray-600 mb-2 uppercase border-b-2 border-black pb-1">Task: {agent.task}</p>
                
                <div className="mt-auto pt-2 flex items-center gap-2 font-bold text-sm">
                  {isPending && <span className="text-gray-400">Waiting...</span>}
                  {isProcessing && <><Loader2 className="w-4 h-4 animate-spin text-blue-600" /> <span className="text-blue-600">Processing...</span></>}
                  {isCompleted && (
                    <div className="flex flex-col gap-1 w-full">
                      <div className="flex items-center gap-1 text-green-600"><CheckCircle2 className="w-4 h-4" /> Done</div>
                      <p className="text-xs bg-gray-100 p-1 border-2 border-black">{agent.output}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Live Agent Chatbot Output */}
      <div className="neu-box bg-white flex flex-col flex-1 min-h-[400px] overflow-hidden">
        <div className="bg-black text-white px-4 py-3 font-black uppercase flex items-center justify-between border-b-4 border-black">
          <span className="flex items-center gap-2"><BrainCircuit className="w-5 h-5" /> Live Agent Communication Hub</span>
          <div className="flex gap-1">
            <div className="w-3 h-3 bg-red-500 border-2 border-black rounded-full" />
            <div className="w-3 h-3 bg-yellow-500 border-2 border-black rounded-full" />
            <div className="w-3 h-3 bg-green-500 border-2 border-black rounded-full" />
          </div>
        </div>
        
        <div className="flex-1 p-4 overflow-y-auto space-y-4 bg-gray-50 flex flex-col max-h-[500px]">
          <AnimatePresence>
            {logs.map((log, i) => {
              const isUser = log.sender === 'User';
              return (
                <motion.div 
                  key={i} 
                  initial={{ opacity: 0, y: 10 }} 
                  animate={{ opacity: 1, y: 0 }} 
                  className={`border-4 border-black p-3 shadow-[4px_4px_0px_black] max-w-[80%] ${isUser ? 'self-end' : 'self-start'} ${log.color}`}
                >
                  <div className="flex items-center gap-2 mb-2 font-black text-xs uppercase border-b-2 border-black pb-1 inline-flex">
                    <span className="bg-black text-white px-1">{log.sender}</span>
                    <ArrowRight className="w-3 h-3" />
                    <span className="bg-white border-2 border-black px-1">{log.receiver}</span>
                  </div>
                  <p className="font-medium text-black text-sm">{log.message}</p>
                </motion.div>
              );
            })}
          </AnimatePresence>
          <div ref={logsEndRef} />
          
          {step < 6 && (
            <div className="flex items-center gap-2 font-bold text-sm text-gray-500 animate-pulse mt-4 self-start">
              <Activity className="w-4 h-4" /> Agents communicating...
            </div>
          )}
        </div>
        
        {/* Chatbot input field */}
        <div className="p-4 border-t-4 border-black bg-white flex gap-2">
          <input 
            type="text" 
            placeholder={step >= 6 ? "Reply to Medical Guide..." : "Agents are currently processing..."}
            disabled={step < 6}
            className="neu-input flex-1 px-4 py-2"
          />
          <button disabled={step < 6} className="neu-btn px-4 py-2 bg-primary">
            <MessageSquare className="w-5 h-5 text-black" />
          </button>
        </div>
      </div>

      <div className="flex justify-center mt-2">
        {step >= 6 ? (
          <Link to={`/tracking/${id || 'SIM-8842'}`} className="neu-btn px-8 py-4 flex items-center gap-2 bg-[#2dd4bf] text-black text-xl hover:translate-y-[2px] hover:translate-x-[2px]">
             PROCEED TO LIVE TRACKING <ArrowRight className="w-6 h-6" />
          </Link>
        ) : (
          <Link to="/" className="neu-btn px-6 py-3 flex items-center gap-2 opacity-50 pointer-events-none bg-gray-200">
             WAITING FOR AGENTS...
          </Link>
        )}
      </div>

    </div>
  );
}
