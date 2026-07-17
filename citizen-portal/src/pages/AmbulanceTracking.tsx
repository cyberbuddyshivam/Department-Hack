import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Truck, Stethoscope, MessageSquare, Clock, Navigation, Gauge, Loader2 } from 'lucide-react';
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix Leaflet's default icon issue
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

/* ======================================================================
   BACKEND INTEGRATION POINT
   Replace `TRACKING_DATA` below with your live payload (API response /
   websocket push). Shape matches your sample LLM output exactly:
   { incident_location }, { ambulance }, { hospital }.
   Everything downstream (routing, animation, ETA, distance) is already
   wired to read from this object — swapping the source is the only
   change needed for backend integration.
   ====================================================================== */

interface TrackingPacket {
  incident_location: { lat: number; lng: number };
  ambulance: {
    id: string;
    current_location: { lat: number; lng: number };
    eta_to_incident_minutes: number;
  };
  hospital: {
    id: string;
    location: { lat: number; lng: number };
    distance_from_incident_km: number;
    eta_incident_to_hospital_minutes: number;
  };
}

interface HospitalReport {
  patient_name: string | null;
  caller_phone: string | null;
  incident_summary: string;
  presenting_complaint: string;
  suspected_diagnosis: string | null;
  severity_score: number;
  ambulance_type: string;
  estimated_arrival_minutes: number | null;
  special_preparations: string[];
  report_generated_at: string;
}

// Fix Leaflet's default icon issue
// Replaced with the verified Santacruz West locality centroid (confirmed
// via a places lookup, not a hand estimate) — solidly on land.
// Animation speeds
const DEMO_PAUSE_AT_INCIDENT_MS = 3000; // pause once ambulance reaches the incident

type LatLng = [number, number];
type Phase = 'loading' | 'to_incident' | 'at_incident' | 'to_hospital' | 'arrived';

/* ----------------------------- geo helpers ----------------------------- */

function haversineKm(a: LatLng, b: LatLng) {
  const R = 6371;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLng = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function bearingDeg(a: LatLng, b: LatLng) {
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const dLng = ((b[1] - a[1]) * Math.PI) / 180;
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

interface RouteMeta {
  coords: LatLng[];
  cumulative: number[]; // cumulative km at each coord index
  totalKm: number;
}

function buildRouteMeta(coords: LatLng[], fallbackTotalKm?: number): RouteMeta {
  const cumulative: number[] = [0];
  for (let i = 1; i < coords.length; i++) {
    cumulative.push(cumulative[i - 1] + haversineKm(coords[i - 1], coords[i]));
  }
  const totalKm = fallbackTotalKm ?? cumulative[cumulative.length - 1] ?? 0;
  return { coords, cumulative, totalKm };
}

// Given a route and a progress fraction t (0..1), return interpolated
// position + heading, walking the route at constant "speed" along its
// actual arc length (so movement stays smooth over uneven segments).
function sampleRoute(route: RouteMeta, t: number): { pos: LatLng; bearing: number } {
  const { coords, cumulative, totalKm } = route;
  if (coords.length < 2) return { pos: coords[0] ?? [0, 0], bearing: 0 };
  const targetDist = Math.max(0, Math.min(1, t)) * totalKm;

  let idx = 0;
  while (idx < cumulative.length - 2 && cumulative[idx + 1] < targetDist) idx++;

  const segStart = coords[idx];
  const segEnd = coords[idx + 1];
  const segStartDist = cumulative[idx];
  const segEndDist = cumulative[idx + 1];
  const segLen = segEndDist - segStartDist || 1e-6;
  const segT = Math.max(0, Math.min(1, (targetDist - segStartDist) / segLen));

  const lat = segStart[0] + (segEnd[0] - segStart[0]) * segT;
  const lng = segStart[1] + (segEnd[1] - segStart[1]) * segT;
  return { pos: [lat, lng], bearing: bearingDeg(segStart, segEnd) };
}

async function fetchOsrmRoute(from: LatLng, to: LatLng): Promise<RouteMeta> {
  const url = `https://router.project-osrm.org/route/v1/driving/${from[1]},${from[0]};${to[1]},${to[0]}?overview=full&geometries=geojson`;
  try {
    const res = await fetch(url);
    const data = await res.json();
    const geomCoords: [number, number][] = data.routes[0].geometry.coordinates; // [lng, lat]
    const coords: LatLng[] = geomCoords.map(([lng, lat]) => [lat, lng]);
    const totalKm = data.routes[0].distance / 1000;
    return buildRouteMeta(coords, totalKm);
  } catch (err) {
    // Fallback only — used if OSRM is unreachable, not the primary path.
    console.warn('OSRM route fetch failed, falling back to direct line', err);
    return buildRouteMeta([from, to]);
  }
}

/* ------------------------------- icons ---------------------------------- */

const dispatchIcon = new L.DivIcon({
  html: `<div class="w-8 h-8 bg-black border-2 border-white rounded-full flex items-center justify-center shadow-[2px_2px_0px_rgba(0,0,0,0.5)]">
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
      <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
  </div>`,
  className: '',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
});

// Icons redesigned for readability at closer zoom: bigger footprint, a real
// medical-cross glyph instead of a text "H", and a proper alert-triangle
// glyph instead of a bare "!" — all drawn as crisp vector SVG (not text) so
// they stay sharp at any zoom level, sharing a consistent black-border /
// drop-shadow "badge" treatment across all three markers.
const hospitalIcon = new L.DivIcon({
  html: `<div class="w-12 h-12 bg-white border-4 border-black rounded-full flex items-center justify-center shadow-[4px_4px_0px_black]">
    <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#ff477e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 6v12M6 12h12"/>
    </svg>
  </div>`,
  className: '',
  iconSize: [48, 48],
  iconAnchor: [24, 24],
});

const incidentIcon = new L.DivIcon({
  html: `<div class="relative w-12 h-12 flex items-center justify-center">
    <div class="absolute w-12 h-12 bg-[#2dd4bf] rounded-full opacity-40 animate-ping"></div>
    <div class="relative w-12 h-12 bg-[#2dd4bf] border-4 border-black rounded-full flex items-center justify-center shadow-[4px_4px_0px_black]">
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12" y2="17.01"/>
      </svg>
    </div>
  </div>`,
  className: '',
  iconSize: [48, 48],
  iconAnchor: [24, 24],
});

function makeAmbulanceIcon(rotation: number) {
  return new L.DivIcon({
    html: `<div style="transform: rotate(${rotation}deg); transition: transform 0.4s linear;" class="w-12 h-12 bg-white border-4 border-black shadow-[4px_4px_0px_black] flex items-center justify-center rounded-full">
      <svg style="transform: rotate(${-rotation}deg);" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ff477e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 17.5V8a2 2 0 0 1 2-2h6l5 5v6.5"/><path d="M2 17.5h3"/><circle cx="7" cy="17.5" r="2"/><circle cx="17" cy="17.5" r="2"/><path d="M9 12V8"/><path d="M7 10h4"/></svg>
    </div>`,
    className: '',
    iconSize: [48, 48],
    iconAnchor: [24, 24],
  });
}

/* --------------------------- camera controller --------------------------- */

// FIX (bugs 1 & 2): the old version keyed its effect on JSON.stringify of a
// two-point bounds array. During `loading` and `to_incident` those two
// points were identical, so the effect never re-fired for `to_incident`
// (zoom looked "dead" on that leg). During `to_hospital` it used the live,
// ever-changing ambulance position, so the effect re-fired on *every*
// animation frame, spamming flyToBounds and making the whole map — road
// line included — appear to jitter/pan continuously.
//
// New approach: fit bounds using the full static route geometry (so the
// whole road is actually in view), and only re-fit once per phase
// transition via an explicit `phase` key — never on a per-frame position
// change.
function CameraController({
  phase,
  focusBounds,
}: {
  phase: Phase;
  focusBounds: LatLng[];
}) {
  const map = useMap();
  const initialized = useRef(false);
  const lastPhase = useRef<Phase | null>(null);

  useEffect(() => {
    if (focusBounds.length < 2) return;
    if (lastPhase.current === phase) return; // only re-fit on an actual phase change
    lastPhase.current = phase;

    const bounds = L.latLngBounds(focusBounds as any);

    // Guard against a zero-size container at first mount (a common cause
    // of a first flyTo/fitBounds silently computing the wrong viewport).
    map.invalidateSize();

    if (!initialized.current) {
      initialized.current = true;
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 17 });
    } else {
      map.flyToBounds(bounds, { padding: [56, 56], maxZoom: 18, duration: 1.1 });
    }
  }, [phase, focusBounds, map]);

  return null;
}

/* -------------------------------- chat ----------------------------------- */

interface ChatMessage {
  sender: 'Agent' | 'User';
  text: string;
}

/* ------------------------------- component -------------------------------- */

export default function AmbulanceTracking() {
  const { id } = useParams();

  const [trackingData, setTrackingData] = useState<TrackingPacket | null>(null);
  const [hospitalReport, setHospitalReport] = useState<HospitalReport | null>(null);

  // Poll Gateway for Realtime Agent Data
  useEffect(() => {
    if (!id) return;
    let isConnected = false;
    const interval: ReturnType<typeof setInterval> = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8000/tracking/${id}`);
        if (res.ok) {
          const data = await res.json();
          if (data.map_data) {
            setTrackingData(data.map_data);
            if (data.hospital_report) {
              setHospitalReport(data.hospital_report);
            }
            if (!isConnected) {
              setMessages(prev => [...prev, { sender: 'Agent', text: 'Realtime telemetry connected to Agent System.' }]);
              isConnected = true;
            }
            clearInterval(interval);
          }
        }
      } catch (err) {}
    }, 2000);
    return () => clearInterval(interval);
  }, [id]);

  const ambulanceStart: LatLng = trackingData ? [
    trackingData.ambulance.current_location.lat,
    trackingData.ambulance.current_location.lng,
  ] : [0,0];
  const incidentPos: LatLng = trackingData ? [trackingData.incident_location.lat, trackingData.incident_location.lng] : [0,0];
  const hospitalPos: LatLng = trackingData ? [trackingData.hospital.location.lat, trackingData.hospital.location.lng] : [0,0];

  const [phase, setPhase] = useState<Phase>('loading');
  const [routeToIncident, setRouteToIncident] = useState<RouteMeta | null>(null);
  const [routeToHospital, setRouteToHospital] = useState<RouteMeta | null>(null);

  const [ambulancePos, setAmbulancePos] = useState<LatLng>(ambulanceStart);
  const [ambulanceBearing, setAmbulanceBearing] = useState(0);
  const [progressPct, setProgressPct] = useState(0);
  const [distanceRemainingKm, setDistanceRemainingKm] = useState<number | null>(null);
  const [etaMinutes, setEtaMinutes] = useState(trackingData?.ambulance?.eta_to_incident_minutes || 5.0);


  const animRef = useRef<number | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([
    { sender: 'Agent', text: 'Hello, I am your Medical AI Assistant. The ambulance is on the way.' },
    { sender: 'Agent', text: 'Please ensure the patient is laying flat. Are they conscious and breathing regularly?' },
  ]);
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Fetch both legs up front from OSRM.
  useEffect(() => {
    if (!trackingData) return;
    let cancelled = false;
    (async () => {
      const [leg1, leg2] = await Promise.all([
        fetchOsrmRoute(ambulanceStart, incidentPos),
        fetchOsrmRoute(incidentPos, hospitalPos),
      ]);
      if (cancelled) return;
      setRouteToIncident(leg1);
      setRouteToHospital(leg2);
      setPhase('to_incident');
    })();
    return () => {
      cancelled = true;
    };
  }, [trackingData?.ambulance?.id, trackingData?.hospital?.id, trackingData?.incident_location?.lat]);

  const animateLeg = useCallback(
    (route: RouteMeta, legEtaMin: number, onDone: () => void) => {
      // Make animation speed proportional to real ETA (1 minute real ETA = 1.5 seconds animation)
      // Cap it between 5 seconds (minimum) and 45 seconds (maximum) so it doesn't take forever but feels real.
      const dynamicDurationMs = Math.max(5000, Math.min(45000, legEtaMin * 1500));
      
      const start = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / dynamicDurationMs);
        const { pos, bearing } = sampleRoute(route, t);
        setAmbulancePos(pos);
        setAmbulanceBearing(bearing);
        setProgressPct(t * 100);
        setDistanceRemainingKm(route.totalKm * (1 - t));
        setEtaMinutes(Math.max(0, legEtaMin * (1 - t)));
        if (t < 1) {
          animRef.current = requestAnimationFrame(step);
        } else {
          onDone();
        }
      };
      animRef.current = requestAnimationFrame(step);
    },
    []
  );

  useEffect(() => {
    if (!trackingData) return;
    if (phase === 'to_incident' && routeToIncident) {
      setAmbulancePos(ambulanceStart);
      const startEta = trackingData.ambulance.eta_to_incident_minutes || 5.0;
      animateLeg(routeToIncident, startEta, () => {
        setPhase('at_incident');
      });
    }
    if (phase === 'at_incident') {
      setProgressPct(100);
      setDistanceRemainingKm(0);
      setEtaMinutes(0);
      const t = setTimeout(() => setPhase('to_hospital'), DEMO_PAUSE_AT_INCIDENT_MS);
      return () => clearTimeout(t);
    }
    if (phase === 'to_hospital' && routeToHospital) {
      setProgressPct(0);
      const hospitalEta = trackingData.hospital.eta_incident_to_hospital_minutes || 5.0;
      animateLeg(routeToHospital, hospitalEta, () => {
        setPhase('arrived');
      });
    }
    if (phase === 'arrived') {
      setProgressPct(100);
      setDistanceRemainingKm(0);
      setEtaMinutes(0);
    }
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, routeToIncident, routeToHospital, trackingData]);

  // FIX (bugs 1 & 2): bounds are now derived from the *entire* route
  // geometry for the active leg (not just two endpoints), and never from a
  // continuously-updating position like ambulancePos. This means the whole
  // road is framed correctly, and the bounds value is stable for the
  // duration of a leg — so CameraController's phase-keyed effect fires
  // exactly once per transition instead of once per frame.
  const focusBounds: LatLng[] = useMemo(() => {
    if (phase === 'loading') return [ambulanceStart, incidentPos];
    if (phase === 'to_incident') {
      return routeToIncident ? routeToIncident.coords : [ambulanceStart, incidentPos];
    }
    if (phase === 'at_incident') return [incidentPos, hospitalPos];
    if (phase === 'to_hospital') {
      return routeToHospital ? routeToHospital.coords : [incidentPos, hospitalPos];
    }
    return [incidentPos, hospitalPos]; // arrived
  }, [phase, routeToIncident, routeToHospital, ambulanceStart, incidentPos, hospitalPos]);

  const activeRoute = phase === 'to_hospital' || phase === 'arrived' ? routeToHospital : routeToIncident;
  const traveledCoords: LatLng[] = activeRoute
    ? activeRoute.coords.filter((_, i) => activeRoute.cumulative[i] <= (progressPct / 100) * activeRoute.totalKm)
    : [];
  const remainingCoords: LatLng[] = activeRoute
    ? activeRoute.coords.filter((_, i) => activeRoute.cumulative[i] >= (progressPct / 100) * activeRoute.totalKm)
    : [];

  const statusText: Record<Phase, string> = {
    loading: 'Calculating route…',
    to_incident: 'En route to incident location',
    at_incident: 'At incident — stabilizing patient',
    to_hospital: `Transporting patient to ${trackingData?.hospital.id.replace(/_/g, ' ') || 'hospital'}`,
    arrived: 'Arrived at hospital',
  };

  const formatEta = (min: number | null | undefined) => {
    if (min == null || isNaN(min)) return '--m --s';
    const totalSec = Math.round(min * 60);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}m ${s.toString().padStart(2, '0')}s`;
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    setMessages((prev) => [...prev, { sender: 'User', text: inputText }]);
    const userInput = inputText;
    setInputText('');
    setTimeout(() => {
      let reply = 'Understood. Please keep monitoring their vitals and stay calm.';
      const lower = userInput.toLowerCase();
      if (lower.includes('not breathing') || lower.includes('no')) {
        reply =
          'URGENT: Begin CPR immediately. Place your hands on the center of their chest and push hard and fast. The ambulance is prioritizing this call.';
      } else if (lower.includes('yes') || lower.includes('breathing')) {
        reply = 'Good. Keep them comfortable. Do not give them anything to eat or drink. Monitor their pulse.';
      } else if (lower.includes('bleeding')) {
        reply = 'Apply firm, direct pressure to the wound using a clean cloth. Do not remove it if it gets soaked, add another layer.';
      }
      setMessages((prev) => [...prev, { sender: 'Agent', text: reply }]);
    }, 1500);
  };

  if (!trackingData) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 h-[600px]">
        <Loader2 className="w-16 h-16 animate-spin text-primary mb-6" />
        <h2 className="text-2xl font-black uppercase tracking-widest">Connecting to Telemetry...</h2>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col p-4 md:p-8 max-w-4xl mx-auto w-full gap-6">
      {/* Header */}
      <div className="flex items-center justify-between neu-box p-4 bg-[#fdf274]">
        <h1 className="text-2xl font-black uppercase flex items-center gap-2">
          <Truck className="w-8 h-8 text-primary" />
          Live Ambulance Tracking
        </h1>
        <div className="font-bold border-2 border-black px-3 py-1 bg-white">
          ID: {id || trackingData.ambulance.id}
        </div>
      </div>

      {/* Map Section */}
      <div className="neu-box p-0 overflow-hidden bg-[#e2ece9] relative h-96 flex flex-col border-4 border-black shadow-[6px_6px_0px_black] z-0">
        <div className="bg-black text-white px-3 py-2 font-black uppercase text-sm z-10 border-b-4 border-black inline-block self-start absolute top-0 left-0">
          Live Map Tracking
        </div>
        <div className="bg-black/80 text-white px-3 py-1.5 font-bold uppercase text-xs z-10 absolute top-0 right-0 flex items-center gap-1.5">
          <Navigation className="w-3.5 h-3.5" />
          {statusText[phase]}
        </div>

        <div className="flex-1 w-full h-full relative z-0">
          <MapContainer center={ambulanceStart} zoom={12} className="w-full h-full z-0" zoomControl={false}>
            <TileLayer
              attribution='&copy; <a href="https://osm.org/copyright">OpenStreetMap</a>'
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            />
            <CameraController phase={phase} focusBounds={focusBounds} />

            <Marker position={ambulanceStart} icon={dispatchIcon}>
              <Popup>Ambulance Dispatch Location</Popup>
            </Marker>
            <Marker position={hospitalPos} icon={hospitalIcon}>
              <Popup>Hospital: {trackingData.hospital.id.replace(/_/g, ' ')}</Popup>
            </Marker>
            <Marker position={incidentPos} icon={incidentIcon}>
              <Popup>Incident location</Popup>
            </Marker>
            <Marker
              position={ambulancePos}
              icon={makeAmbulanceIcon(ambulanceBearing)}
              zIndexOffset={1000}
            />

            {/* Traveled portion of the active leg */}
            {traveledCoords.length > 1 && (
              <Polyline positions={traveledCoords} pathOptions={{ color: '#2dd4bf', weight: 6 }} />
            )}
            {/* Remaining portion of the active leg */}
            {remainingCoords.length > 1 && (
              <Polyline
                positions={remainingCoords}
                pathOptions={{ color: 'black', weight: 4, dashArray: '2, 10', opacity: 0.5 }}
              />
            )}
            {/* Faint reference of the leg already completed */}
            {phase !== 'to_incident' && phase !== 'loading' && routeToIncident && (
              <Polyline
                positions={routeToIncident.coords}
                pathOptions={{ color: 'black', weight: 3, opacity: 0.15 }}
              />
            )}
          </MapContainer>
        </div>
      </div>

      {/* Live Stats Section */}
      <div className="neu-box p-6 bg-white flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="bg-[#2dd4bf] p-3 border-4 border-black shadow-[4px_4px_0px_black]">
            <Clock className="w-8 h-8 text-black animate-pulse" />
          </div>
          <div>
            <h2 className="text-xl font-black uppercase">Estimated Arrival</h2>
            <p className="font-bold text-gray-500 text-sm">{statusText[phase]}</p>
          </div>
        </div>
        <div className="text-5xl font-black text-[#ff477e] drop-shadow-[2px_2px_0px_black]">
          {formatEta(etaMinutes)}
        </div>
      </div>

      <div className="neu-box p-4 bg-white flex items-center gap-4">
        <Gauge className="w-6 h-6 shrink-0" />
        <div className="flex-1">
          <div className="flex justify-between font-bold text-xs uppercase mb-1">
            <span>Route Progress</span>
            <span>
              {progressPct.toFixed(0)}% · {distanceRemainingKm !== null ? `${distanceRemainingKm.toFixed(1)} km left` : '—'}
            </span>
          </div>
          <div className="w-full h-3 bg-gray-200 border-2 border-black overflow-hidden">
            <motion.div
              className="h-full bg-[#ff477e]"
              animate={{ width: `${progressPct}%` }}
              transition={{ ease: 'linear', duration: 0.2 }}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-6">
        {/* Medical Guide Chatbot Section */}
        <div className="neu-box bg-[#fcd5ce] flex flex-col flex-1 h-[450px] overflow-hidden">
          <div className="bg-black text-white px-4 py-3 font-black uppercase text-sm border-b-4 border-black flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Stethoscope className="w-5 h-5" /> Agent 5: Medical Guide
            </span>
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
                    <p className="font-black text-xs uppercase mb-1 border-b-2 border-black inline-block">
                      {msg.sender}
                    </p>
                    <p className="font-bold text-sm text-black">{msg.text}</p>
                  </motion.div>
                );
              })}
            </AnimatePresence>
            <div ref={messagesEndRef} />
          </div>

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

        {/* Hospital Admission Report Section */}
        {hospitalReport && (
          <div className="neu-box bg-white flex flex-col flex-1 h-[450px] overflow-hidden">
            <div className="bg-black text-white px-4 py-3 font-black uppercase text-sm border-b-4 border-black flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Truck className="w-5 h-5" /> Admission Formalities Agent
              </span>
              <span className="bg-[#2dd4bf] text-black font-bold px-2 py-0.5 text-xs">REPORT SENT</span>
            </div>
            
            <div className="p-4 overflow-y-auto flex flex-col gap-3">
              <div className="border-2 border-black p-3 bg-[#e2ece9]">
                <h3 className="font-black uppercase text-xs text-gray-500">Incident Summary</h3>
                <p className="font-bold text-sm">{hospitalReport.incident_summary}</p>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                <div className="border-2 border-black p-3 bg-[#fdf274]">
                  <h3 className="font-black uppercase text-xs text-gray-500">Severity</h3>
                  <p className="font-bold text-lg">{hospitalReport.severity_score} / 10</p>
                </div>
                <div className="border-2 border-black p-3 bg-white">
                  <h3 className="font-black uppercase text-xs text-gray-500">Ambulance</h3>
                  <p className="font-bold text-lg uppercase">{hospitalReport.ambulance_type}</p>
                </div>
              </div>

              <div className="border-2 border-black p-3 bg-[#fff0ed]">
                <h3 className="font-black uppercase text-xs text-gray-500">Presenting Complaint</h3>
                <p className="font-bold text-sm">{hospitalReport.presenting_complaint}</p>
              </div>

              {hospitalReport.suspected_diagnosis && (
                <div className="border-2 border-black p-3 bg-white">
                  <h3 className="font-black uppercase text-xs text-gray-500">Suspected Diagnosis</h3>
                  <p className="font-bold text-sm">{hospitalReport.suspected_diagnosis}</p>
                </div>
              )}

              {hospitalReport.special_preparations?.length > 0 && (
                <div className="border-2 border-black p-3 bg-[#ffc2d1]">
                  <h3 className="font-black uppercase text-xs text-gray-500 mb-1">Required Preparations</h3>
                  <ul className="list-disc list-inside font-bold text-sm">
                    {hospitalReport.special_preparations.map((prep, i) => (
                      <li key={i}>{prep}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
