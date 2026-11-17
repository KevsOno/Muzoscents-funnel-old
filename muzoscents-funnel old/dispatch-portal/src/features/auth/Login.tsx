import { useEffect } from 'react';

export default function Login() {
  useEffect(() => {
    // Check for the global token
    const token = localStorage.getItem('access_token');
    if (token) {
      // If they have a token, reload the app so React picks up the session
      window.location.reload();
    } else {
      // Otherwise, send them to the main central login page
      window.location.href = '/kdsiginin';
    }
  }, []);

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f1f5f9' }}>
      <div style={{
        border: '2px solid #e5e7eb',
        borderTop: '2px solid #3b82f6',
        borderRadius: '50%',
        width: '30px',
        height: '30px',
        animation: 'spin 0.6s linear infinite'
      }}></div>
      <style>{`@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
