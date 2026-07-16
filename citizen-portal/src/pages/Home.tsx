import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { ShieldAlert, Phone, Activity } from 'lucide-react';

export default function Home() {
  const navigate = useNavigate();

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 relative overflow-hidden">
      {/* Decorative neubrutalism background elements */}
      <div className="absolute top-10 left-10 w-24 h-24 bg-accent border-4 border-black rounded-full z-0" />
      <div className="absolute bottom-10 right-10 w-32 h-32 bg-primary border-4 border-black z-0 rotate-12" />

      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="max-w-2xl w-full text-center space-y-8 z-10"
      >
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-white border-4 border-black shadow-[4px_4px_0px_black] rounded-full">
            <ShieldAlert className="w-16 h-16 text-primary" />
          </div>
        </div>
        
        <h1 className="text-6xl md:text-8xl font-black tracking-tight uppercase text-black drop-shadow-[4px_4px_0px_white]">
          AEGIS
        </h1>
        
        <p className="text-lg md:text-xl font-bold tracking-widest text-black bg-white/80 p-4 border-4 border-black rounded-sm inline-block shadow-[4px_4px_0px_black] uppercase -rotate-2 mt-4">
          Under the surveillance
        </p>

        <div className="pt-8 flex justify-center">
          <button
            onClick={() => navigate('/request')}
            className="neu-btn px-8 py-4 flex items-center justify-center text-lg gap-2 cursor-pointer w-full md:w-auto"
          >
            <Activity className="w-6 h-6 animate-pulse" />
            REPORT EMERGENCY NOW
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-16 border-t-4 border-black mt-16">
          <div className="neu-box p-6 flex flex-col items-center text-center bg-[#cce3de]">
            <Phone className="w-10 h-10 text-black mb-4" />
            <h3 className="font-black text-xl mb-2 uppercase">Multi-Channel</h3>
            <p className="font-medium text-black">Accessible via Web, Voice, SMS, and WhatsApp.</p>
          </div>
          <div className="neu-box p-6 flex flex-col items-center text-center bg-[#fdf0d5]">
            <Activity className="w-10 h-10 text-black mb-4" />
            <h3 className="font-black text-xl mb-2 uppercase">AI Triage</h3>
            <p className="font-medium text-black">Autonomous medical assessment and resource matching.</p>
          </div>
          <div className="neu-box p-6 flex flex-col items-center text-center bg-[#fcd5ce]">
            <ShieldAlert className="w-10 h-10 text-black mb-4" />
            <h3 className="font-black text-xl mb-2 uppercase">Instant Dispatch</h3>
            <p className="font-medium text-black">Direct coordination with nearest available hospitals.</p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
