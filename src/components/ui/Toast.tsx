import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

type ToastKind = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

const ToastContext = createContext<(kind: ToastKind, message: string) => void>(() => {});

// Ranglar CSS tokenlaridan — qorong'i mavzuda ham o'qiladi
// (ilgari qat'iy emerald-50/red-50 edi: qorong'i fonda oq quti ko'rinardi).
const STYLE: Record<ToastKind, { box: string; icon: typeof Info }> = {
  success: { box: 'border-success bg-success-soft text-success', icon: CheckCircle2 },
  error: { box: 'border-danger bg-danger-soft text-danger', icon: AlertTriangle },
  info: { box: 'border-info bg-info-soft text-info', icon: Info },
};

/** Qisqa xabarlar ("Saqlandi", "Xatolik") — konsolga yozish o'rniga
 *  foydalanuvchiga ko'rinadigan natija. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((list) => list.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++;
      setItems((list) => [...list.slice(-3), { id, kind, message }]);
      window.setTimeout(() => dismiss(id), kind === 'error' ? 7000 : 4500);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" role="status" aria-live="polite">
        {items.map((item) => {
          const { box, icon: Icon } = STYLE[item.kind];
          return (
            <div key={item.id} className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm shadow-lg ${box}`}>
              <Icon size={16} className="mt-0.5 shrink-0" />
              <p className="min-w-0 flex-1">{item.message}</p>
              <button type="button" onClick={() => dismiss(item.id)} aria-label="Yopish" className="rounded p-0.5 opacity-60 hover:opacity-100">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastContext);
  return useMemo(
    () => ({
      success: (message: string) => push('success', message),
      error: (message: string) => push('error', message),
      info: (message: string) => push('info', message),
    }),
    [push],
  );
}
