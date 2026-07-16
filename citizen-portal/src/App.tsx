import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import EmergencyRequest from './pages/EmergencyRequest';
import RequestStatus from './pages/RequestStatus';
import AmbulanceTracking from './pages/AmbulanceTracking';

function App() {
  return (
    <Router>
      <div className="min-h-screen font-sans flex flex-col">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/request" element={<EmergencyRequest />} />
          <Route path="/status/:id" element={<RequestStatus />} />
          <Route path="/tracking/:id" element={<AmbulanceTracking />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
