import { Component, ErrorInfo, ReactNode } from 'react';

interface Props { children: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  public state: State = { hasError: false, error: null };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen flex-col items-center justify-center p-6 text-center">
          <h1 className="text-2xl font-bold text-slate-800">Something went wrong</h1>
          <p className="mt-2 text-slate-500">Please refresh the page. If the problem persists, contact support.</p>
          <button onClick={() => window.location.reload()} className="mt-4 rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700">
            Refresh
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
