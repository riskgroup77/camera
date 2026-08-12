import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertOctagon, RotateCcw } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Kutilmagan xatolik:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
        <div className="glass flex max-w-md flex-col items-center gap-3 p-8 text-center">
          <AlertOctagon size={32} className="text-red-500" />
          <h1 className="text-base font-extrabold text-slate-900 dark:text-slate-100">
            Kutilmagan xatolik yuz berdi
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Sahifani qayta yuklab ko'ring. Muammo davom etsa, tizim administratoriga murojaat qiling.
          </p>
          <p className="w-full overflow-x-auto rounded-lg bg-slate-900/5 p-2 text-left font-mono text-[11px] text-slate-500 dark:bg-white/5 dark:text-slate-400">
            {this.state.error.message}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700"
          >
            <RotateCcw size={14} />
            Sahifani qayta yuklash
          </button>
        </div>
      </div>
    );
  }
}
