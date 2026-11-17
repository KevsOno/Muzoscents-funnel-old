import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { DispatchDashboard } from './features/dispatch/DispatchDashboard';
import { DriverShift } from './features/driver/DriverShift';

export default function App() {
  // Read the role from localStorage to decide the default landing page
  const role = (localStorage.getItem('user_role') || 'owner').toLowerCase();

  return (
    <Router basename="/dispatch">
      <Routes>
        <Route path="/" element={<AppShell />}>
          {/* If the user is a driver, show the Shift view. Otherwise, show the Map. */}
          <Route index element={role === 'driver' ? <DriverShift /> : <DispatchDashboard />} />
          
          {/* Explicit routes for manual navigation */}
          <Route path="driver" element={<DriverShift />} />
          <Route path="dashboard" element={<DispatchDashboard />} />
          
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Router>
  );
}
