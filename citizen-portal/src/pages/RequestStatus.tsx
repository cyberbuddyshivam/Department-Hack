import { useState, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, ArrowRight, BrainCircuit, MapPin, Truck, Stethoscope, MessageSquare } from 'lucide-react';

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
    // Scroll to bottom of logs
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    const simulationSequence = async () => {
      // Step 0: Gateway
      addLog('Gateway', 'Agent 1', 'Patient distress signal received. Coord: [34.05, -118.24]. Locate nearest medical facilities.', 'bg-[#cce3de]');
      
      await delay(3000);
      setStep(1);
      // Step 1: Agent 1 (Locator)
      addLog('Agent 1', 'Agent 2', 'Identified 3 nearby facilities: City Gen (2km), Mercy Med (3km), Care Point (3.5km). Evaluate fastest route.', 'bg-[#fdf0d5]');
      
      await delay(4000);
      setStep(2);
      // Step 2: Agent 2 (Traffic Analyzer)
      addLog('Agent 2', 'Agent 3', 'Traffic heavy on I-5. City Gen delayed by 15m. Mercy Med route clear. ETA: 6 mins. Select Mercy Med.', 'bg-[#ffc2d1]');
      
      await delay(4000);
      setStep(3);
      // Step 3: Agent 3 (Coordinator)
      addLog('Agent 3', 'Mercy Med', 'CRITICAL ALERT: Incoming trauma patient. ETA 6 mins. Requesting immediate bed preparation.', 'bg-[#ccfbf1]');
      
      await delay(3000);
      addLog('Mercy Med', 'Agent 3', 'Bed confirmed. Trauma team on standby. Ambulance dispatched.', 'bg-white');

      await delay(2000);
      setStep(4);
      // Step 4: Agents 4 & 5 (Surveillance & Medical Guide)
      addLog('Agent 3', 'Agent 4', 'Ambulance dispatched. Initiate live surveillance.', 'bg-[#ccfbf1]');
      addLog('Agent 3', 'Agent 5', 'Dispatch confirmed. Initiate patient medical support.', 'bg-[#ccfbf1]');
    };

    simulationSequence();
  }, []);

  const delay = (ms: number) => new Promise(res => setTimeout(res, ms));

  const addLog = (sender: string, receiver: string, message: string, color: string) => {
    setLogs(prev => [...prev, { sender, receiver, message, color }]);
  };

  return (
    <div className="flex-1 flex flex-col p-4 md:p-8 max-w-6xl mx-auto w-full gap-6">
      
      <div className="flex items-center justify-between neu-box p-4 bg-[#fdf274]">
        <h1 className="text-2xl font-black uppercase flex items-center gap-2">
          <Activity className="w-8 h-8 animate-pulse text-primary" />
          Live AI Dispatch Simulation
        </h1>
        <div className="font-bold border-2 border-black px-3 py-1 bg-white">ID: {id || 'SIM-8842'}</div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-[600px]">
        {/* Left Column: Map & Active Agents */}
        <div className="flex flex-col gap-6">
          {/* Map Simulation */}
          <div className="neu-box p-0 overflow-hidden bg-[#e2ece9] relative h-64 flex flex-col border-4 border-black">
            <div className="bg-black text-white px-3 py-1 font-black uppercase text-sm z-10 border-b-4 border-black inline-block self-start">
              Live Tracker Map
            </div>
            
            <div className="flex-1 relative w-full h-full p-4">
              {/* Patient Location */}
              <div className="absolute top-1/2 left-1/4 transform -translate-y-1/2 flex flex-col items-center z-10">
                <div className="w-6 h-6 bg-primary border-4 border-black rounded-full animate-ping absolute opacity-50" />
                <MapPin className="w-8 h-8 text-primary relative z-10 drop-shadow-[2px_2px_0px_black]" />
                <span className="font-bold text-xs bg-white px-1 border-2 border-black mt-1">PATIENT</span>
              </div>

              {/* Hospitals (Step 1+) */}
              <AnimatePresence>
                {step >= 1 && (
                  <>
                    <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute top-1/4 right-1/4 flex flex-col items-center">
                      <div className="w-6 h-6 bg-white border-4 border-black flex items-center justify-center font-bold text-xs shadow-[2px_2px_0px_black]">H1</div>
                    </motion.div>
                    <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute top-3/4 right-1/3 flex flex-col items-center">
                      <div className="w-6 h-6 bg-white border-4 border-black flex items-center justify-center font-bold text-xs shadow-[2px_2px_0px_black]">H3</div>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>

              {/* Selected Hospital (Step 2+) */}
              <AnimatePresence>
                {step >= 1 && (
                  <motion.div 
                    initial={{ scale: 0 }} 
                    animate={{ scale: step >= 2 ? 1.5 : 1 }} 
                    className={`absolute top-1/2 right-10 transform -translate-y-1/2 flex flex-col items-center transition-all duration-500 z-10`}
                  >
                    <div className={`w-8 h-8 ${step >= 2 ? 'bg-green-400' : 'bg-white'} border-4 border-black flex items-center justify-center font-bold text-sm shadow-[4px_4px_0px_black]`}>
                      H2
                    </div>
                    {step >= 2 && <span className="font-bold text-xs bg-white px-1 border-2 border-black mt-2">MERCY MED</span>}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Route Line (Step 2+) */}
              {step >= 2 && (
                <svg className="absolute inset-0 w-full h-full pointer-events-none z-0" style={{ zIndex: 0 }}>
                  <line x1="25%" y1="50%" x2="calc(100% - 2.5rem)" y2="50%" stroke="black" strokeWidth="4" strokeDasharray="8 8" className="animate-[dash_1s_linear_infinite]" />
                </svg>
              )}

              {/* Ambulance (Step 4+) */}
              {step >= 4 && (
                <motion.div 
                  initial={{ right: '2.5rem', top: '50%' }}
                  animate={{ right: '75%', top: '50%' }}
                  transition={{ duration: 5, repeat: Infinity, repeatType: 'reverse' }}
                  className="absolute transform -translate-y-1/2 z-20"
                >
                  <div className="bg-white border-4 border-black p-1 shadow-[4px_4px_0px_black]">
                    <Truck className="w-6 h-6 text-primary" />
                  </div>
                </motion.div>
              )}
            </div>
          </div>

          {/* Medical Guide Agent (Step 4+) */}
          {step >= 4 ? (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="neu-box bg-[#fcd5ce] flex-1 flex flex-col overflow-hidden">
              <div className="bg-black text-white px-3 py-2 font-black uppercase text-sm border-b-4 border-black flex items-center justify-between">
                <span className="flex items-center gap-2"><Stethoscope className="w-4 h-4" /> Agent 5: Medical Guide</span>
                <span className="bg-red-500 text-white px-2 py-0.5 text-xs animate-pulse">ACTIVE</span>
              </div>
              <div className="p-4 flex-1 flex flex-col gap-3">
                <div className="bg-white border-4 border-black p-3 shadow-[4px_4px_0px_black] rounded-br-2xl rounded-tr-2xl rounded-tl-sm w-[90%] self-start">
                  <p className="font-bold text-sm">Hello, I am your Medical AI Assistant. The ambulance is on the way (ETA: 5m 20s).</p>
                </div>
                <div className="bg-white border-4 border-black p-3 shadow-[4px_4px_0px_black] rounded-br-2xl rounded-tr-2xl rounded-tl-sm w-[90%] self-start">
                  <p className="font-bold text-sm">Please ensure the patient is laying flat. Are they conscious and breathing regularly?</p>
                </div>
                
                <div className="mt-auto relative">
                  <input type="text" placeholder="Reply to Medical Guide..." disabled className="neu-input w-full p-3 pr-12 text-sm bg-gray-100" />
                  <button disabled className="absolute right-2 top-2 p-1 bg-black text-white border-2 border-black"><MessageSquare className="w-4 h-4" /></button>
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="neu-box bg-gray-100 flex-1 flex items-center justify-center border-dashed opacity-50">
              <p className="font-bold text-gray-500">Medical Guide Offline (Awaiting Dispatch)</p>
            </div>
          )}
        </div>

        {/* Right Column: Communication Terminal */}
        <div className="neu-box bg-white flex flex-col h-full overflow-hidden border-4 border-black">
          <div className="bg-black text-white px-4 py-3 font-black uppercase flex items-center justify-between border-b-4 border-black">
            <span className="flex items-center gap-2"><BrainCircuit className="w-5 h-5" /> Agent Communication Log</span>
            <div className="flex gap-1">
              <div className="w-3 h-3 bg-red-500 border-2 border-black rounded-full" />
              <div className="w-3 h-3 bg-yellow-500 border-2 border-black rounded-full" />
              <div className="w-3 h-3 bg-green-500 border-2 border-black rounded-full" />
            </div>
          </div>
          
          <div className="flex-1 p-4 overflow-y-auto space-y-4 bg-gray-50 max-h-[600px]">
            <AnimatePresence>
              {logs.map((log, i) => (
                <motion.div 
                  key={i} 
                  initial={{ opacity: 0, x: -20 }} 
                  animate={{ opacity: 1, x: 0 }} 
                  className={`border-4 border-black p-3 shadow-[4px_4px_0px_black] ${log.color}`}
                >
                  <div className="flex items-center gap-2 mb-2 font-black text-xs uppercase border-b-2 border-black pb-1 inline-flex">
                    <span className="bg-black text-white px-1">{log.sender}</span>
                    <ArrowRight className="w-3 h-3" />
                    <span className="bg-white border-2 border-black px-1">{log.receiver}</span>
                  </div>
                  <p className="font-medium text-black text-sm">{log.message}</p>
                </motion.div>
              ))}
            </AnimatePresence>
            <div ref={logsEndRef} />
            
            {step < 4 && (
              <div className="flex items-center gap-2 font-bold text-sm text-gray-500 animate-pulse mt-4">
                <Activity className="w-4 h-4" /> Agents Processing...
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex justify-center mt-4">
        <Link to="/" className="neu-btn px-6 py-3 flex items-center gap-2">
           RETURN TO DASHBOARD
        </Link>
      </div>

    </div>
  );
}
