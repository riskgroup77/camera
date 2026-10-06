import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface Props {
  title: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Bitta panel ichidagi kutilmagan xato faqat O'SHA panelni almashtiradi.
 *  Ilgari guruh panelidagi bitta formatlash xatosi (2026-10-06, "Invalid
 *  time value") butun pultni "Kutilmagan xatolik" sahifasiga aylantirardi —
 *  kameralar va jadval ham yo'qolardi. */
export default class PanelBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Panel xatosi (${this.props.title}):`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
        <AlertTriangle size={22} className="text-warning" aria-hidden="true" />
        <p className="text-[13px] font-semibold text-fg">Bu bo‘limni ko‘rsatishda xatolik yuz berdi</p>
        <p className="max-w-[90%] truncate font-mono text-[11px] text-muted" title={this.state.error.message}>
          {this.state.error.message}
        </p>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            this.setState({ error: null });
          }}
          className="mt-1 inline-flex items-center gap-1.5 rounded-control bg-primary-soft px-3 py-1.5 text-[12px] font-semibold text-primary transition-colors hover:bg-primary/15"
        >
          <RotateCcw size={13} aria-hidden="true" /> Qayta urinish
        </button>
      </div>
    );
  }
}
