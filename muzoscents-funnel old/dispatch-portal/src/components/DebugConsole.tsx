import React, { useState, useEffect } from 'react';

export function DebugConsole() {
  const [errors, setErrors] = useState<string[]>([]);
  const [isOpen, setIsOpen] = useState(true);
  const [storage, setStorage] = useState<Record<string, string>>({});

  useEffect(() => {
    // Capture global JS errors
    const handleError = (event: ErrorEvent) => {
      setErrors((prev) => [...prev, `Error: ${event.message}`]);
    };
    // Capture unhandled promise rejections (like failed API calls)
    const handleRejection = (event: PromiseRejectionEvent) => {
      setErrors((prev) => [...prev, `Promise Rejection: ${event.reason?.message || event.reason}`]);
    };

    window.addEventListener('error', handleError);
    window.addEventListener('unhandledrejection', handleRejection);

    // Read LocalStorage
    const ls: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) ls[key] = localStorage.getItem(key) || '';
    }
    setStorage(ls);

    return () => {
      window.removeEventListener('error', handleError);
      window.removeEventListener('unhandledrejection', handleRejection);
    };
  }, []);

  useEffect(() => {
    const originalError = console.error;
    const originalWarn = console.warn;

    console.error = (...args) => {
      setErrors((prev) => [...prev, `Console Error: ${args.map(String).join(' ')}`]);
      originalError(...args);
    };
    
    console.warn = (...args) => {
      setErrors((prev) => [...prev, `Console Warn: ${args.map(String).join(' ')}`]);
      originalWarn(...args);
    };

    // overrideConsole
    return () => {
      console.error = originalError;
      console.warn = originalWarn;
    };
  }, []);


  if (!isOpen) {
    return (
      <button 
        onClick={() => setIsOpen(true)}
        style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 99999, background: '#ef4444', color: 'white', padding: '10px 15px', borderRadius: '8px', fontWeight: 'bold' }}
      >
        Open Debugger
      </button>
    );
  }

  return (
    <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 99999, width: '400px', maxHeight: '500px', background: '#1e293b', color: '#e2e8f0', border: '1px solid #475569', borderRadius: '8px', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', fontFamily: 'monospace', fontSize: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px', background: '#0f172a', borderTopLeftRadius: '8px', borderTopRightRadius: '8px', fontWeight: 'bold' }}>
        <span>🐞 Visual Debug Console</span>
        <button onClick={() => setIsOpen(false)} style={{ color: '#ef4444', background: 'transparent', border: 'none', cursor: 'pointer' }}>Close</button>
      </div>
      
      <div style={{ padding: '10px', overflowY: 'auto', flex: 1 }}>
        <div style={{ marginBottom: '15px' }}>
          <div style={{ color: '#38bdf8', marginBottom: '5px' }}>📁 LocalStorage State:</div>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {JSON.stringify(storage, null, 2)}
          </pre>
        </div>

        <div>
          <div style={{ color: '#f87171', marginBottom: '5px' }}>🚨 Errors ({errors.length}):</div>
          {errors.length === 0 ? (
            <div style={{ color: '#4ade80' }}>No runtime errors caught.</div>
          ) : (
            errors.map((err, i) => (
              <div key={i} style={{ marginBottom: '5px', padding: '5px', background: '#450a0a', borderLeft: '3px solid #ef4444' }}>
                {err}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
