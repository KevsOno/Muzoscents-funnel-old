import React from 'react';
import { createRoot } from 'react-dom/client';
import { Toaster } from 'react-hot-toast';
;
import './index.css';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DebugConsole } from './components/DebugConsole';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
      <Toaster position="top-right" />
    </ErrorBoundary>
  </React.StrictMode>,
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <DebugConsole />
  </React.StrictMode>,
);