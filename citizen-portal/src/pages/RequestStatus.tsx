import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
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
  const location = useLocation();
  const [step, setStep] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Removed auto-scroll so user can read agent traces at their own pace

  const [agentTrace, setAgentTrace] = useState<any[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [finalData, setFinalData] = useState<any>(null);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const fetchTrace = async () => {
      try {
        const res = await fetch(`http://localhost:8000/tracking/${id}`);
        if (res.ok) {
          const data = await res.json();
          if (data.agent_trace) {
            setAgentTrace(data.agent_trace);
            
            const newLogs: LogEntry[] = data.agent_trace.map((agent: any) => ({
                 sender: agent.agent_name,
                 receiver: 'System',
                 message: agent.reasoning || JSON.stringify(agent.result),
                 color: 'bg-white'
            }));
            setLogs(newLogs);
          }
          if (data.status === "completed") {
            setFinalData(data);
            setStep(6);
            setIsLoaded(true);
            if (interval) clearInterval(interval);
          }
        }
      } catch (err) {
        console.error("Failed to fetch trace", err);
      }
    };
    
    fetchTrace();
    interval = setInterval(fetchTrace, 2000);
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [id]);

  const agents = agentTrace.map((agent: any, idx: number) => ({
    id: idx + 1,
    name: agent.agent_name,
    icon: BrainCircuit,
    color: "bg-[#e2ece9]",
    task: `Analyzed`,
    output: `Thought for ${(agent.latency_ms / 1000).toFixed(1)}s`
  }));


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
          {location.state?.userInput || '"My father collapsed, he is not breathing properly." \nLocation: Lat 34.0522, Lng -118.2437'}
        </p>
      </div>

      {/* Agent Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {agents.length > 0 ? agents.map((agent: any) => {
          const Icon = agent.icon;
          return (
            <div 
              key={agent.name} 
              className={`neu-box flex flex-col overflow-hidden transition-opacity duration-500 opacity-100`}
            >
              <div className={`p-3 border-b-4 border-black flex items-center justify-between ${agent.color}`}>
                <span className="font-black text-sm uppercase truncate pr-2">{agent.name}</span>
                <Icon className="w-5 h-5 flex-shrink-0" />
              </div>
              <div className="p-3 flex-1 flex flex-col bg-white">
                <div className="mt-auto pt-2 flex items-center gap-2 font-bold text-sm">
                  <div className="flex flex-col gap-1 w-full">
                    <div className="flex items-center gap-1 text-green-600"><CheckCircle2 className="w-4 h-4" /> {agent.task}</div>
                    <p className="text-xs bg-gray-100 p-1 border-2 border-black">{agent.output}</p>
                  </div>
                </div>
              </div>
            </div>
          );
        }) : null}
        
        {!isLoaded && (
          <div className="col-span-full neu-box p-6 flex flex-col items-center justify-center bg-[#fdf0d5] border-dashed border-4 border-black">
             <Loader2 className="w-8 h-8 animate-spin mb-2" />
             <p className="font-bold uppercase">Agent is thinking...</p>
          </div>
        )}
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
          
          {logs.length === 0 && !isLoaded && (
            <div className="flex items-center gap-2 font-bold text-sm text-gray-500 animate-pulse mt-4 self-start">
              <Activity className="w-4 h-4" /> Fetching live reasoning from agents...
            </div>
          )}
          
          {!isLoaded && logs.length > 0 && (
             <div className="flex items-center gap-2 font-bold text-sm text-blue-500 animate-pulse mt-4 self-start">
               <Activity className="w-4 h-4" /> Agent is analyzing next step...
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

      {isLoaded && finalData?.map_data && (
        <div className="neu-box p-6 bg-[#ccfbf1] mt-4">
          <h3 className="text-xl font-black border-b-4 border-black pb-2 mb-4 uppercase flex items-center gap-2"><MapPin className="w-6 h-6" /> Final Dispatch Verdict</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white p-3 border-2 border-black">
              <p className="font-black text-sm uppercase text-gray-500">Incident Location</p>
              <p className="font-bold">Lat: {finalData.map_data.incident_location.lat.toFixed(4)}</p>
              <p className="font-bold">Lng: {finalData.map_data.incident_location.lng.toFixed(4)}</p>
            </div>
            <div className="bg-white p-3 border-2 border-black">
              <p className="font-black text-sm uppercase text-gray-500">Ambulance ({finalData.map_data.ambulance.id})</p>
              <p className="font-bold">Lat: {finalData.map_data.ambulance.current_location.lat.toFixed(4)}</p>
              <p className="font-bold">Lng: {finalData.map_data.ambulance.current_location.lng.toFixed(4)}</p>
              <p className="font-bold text-[#ff477e]">ETA: {finalData.map_data.ambulance.eta_to_incident_minutes ?? '--'} mins</p>
            </div>
            <div className="bg-white p-3 border-2 border-black">
              <p className="font-black text-sm uppercase text-gray-500">Hospital ({finalData.map_data.hospital.id})</p>
              <p className="font-bold">Lat: {finalData.map_data.hospital.location.lat.toFixed(4)}</p>
              <p className="font-bold">Lng: {finalData.map_data.hospital.location.lng.toFixed(4)}</p>
              <p className="font-bold">Dist: {finalData.map_data.hospital.distance_from_incident_km ?? '--'} km</p>
            </div>
          </div>
          {finalData.brief && (
            <div className="mt-4 bg-white p-3 border-2 border-black">
               <p className="font-black text-sm uppercase text-gray-500 mb-1">Agent Action Brief</p>
               <p className="font-bold text-sm">{finalData.brief}</p>
            </div>
          )}
        </div>
      )}

      <div className="flex justify-center mt-2">
        {isLoaded ? (
          <Link to={`/tracking/${id || 'SIM-8842'}`} className="neu-btn px-8 py-4 flex items-center gap-2 bg-[#2dd4bf] text-black text-xl hover:translate-y-[2px] hover:translate-x-[2px]">
             PROCEED TO LIVE TRACKING <ArrowRight className="w-6 h-6" />
          </Link>
        ) : (
          <div className="neu-btn px-6 py-3 flex items-center gap-2 opacity-50 pointer-events-none bg-gray-200">
             WAITING FOR AGENTS...
          </div>
        )}
      </div>

    </div>
  );
}
