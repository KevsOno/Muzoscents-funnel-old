import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import DispatchDashboard from './features/dispatch/DispatchDashboard';

export default function App() {
  return (
    <Router basename="/dispatch">
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<DispatchDashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Router>
  );
}
