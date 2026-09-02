import { ListChecks, Loader2, LogIn } from 'lucide-react';
import Badge from '../Badge';
import { useAuth } from '../../lib/auth';
import { useLiveEvents } from '../../lib/realtime';
import { useServerPage } from '../../lib/useServerPage';
import type { AIEvent } from '../../types';

const SEVERITY_TONE: Record<AIEvent['severity'], 'green' | 'amber' | 'red'> = {
  past: 'green',
  "o'rta": 'amber',
  yuqori: 'red',
};

const PAGE_SIZE = 6;

/** O'ng panelning o'rta qismi — Hodisalar jurnalidagi kabi so'nggi
 * hodisalarni ixcham ro'yxatda ko'rsatadi, jonli (WebSocket) yangilanadi. */
export default function EventsLogPanel() {
  const { token } = useAuth();
  const { items: events, page, loading, error, reload } = useServerPage<AIEvent>('/api/events', {}, PAGE_SIZE);

  useLiveEvents(() => {
    if (page === 1) reload();
  }, !!token);

  return (
    <div className="glass p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-sm font-extrabold text-slate-900 dark:text-slate-100">
        <ListChecks size={15} className="text-indigo-500" />
        Hodisalar jurnali
      </h3>

      {!token ? (
        <p className="flex items-center gap-1.5 rounded-lg bg-white/60 px-3 py-2.5 text-xs text-slate-500 dark:bg-white/5 dark:text-slate-400">
          <LogIn size={13} />
          Ko'rish uchun tizimga kiring
        </p>
      ) : loading && events.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-slate-400">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : error ? (
        <p className="text-[11px] font-medium text-red-600 dark:text-red-400">{error}</p>
      ) : events.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 py-6 text-center text-[11px] text-slate-400 dark:border-white/10 dark:text-slate-500">
          Hodisa topilmadi
        </p>
      ) : (
        <ul className="space-y-2">
          {events.map((e) => (
            <li key={e.id} className="rounded-lg bg-white/60 p-2.5 text-xs dark:bg-white/5">
              <div className="mb-0.5 flex items-center justify-between gap-2">
                <span className="truncate font-semibold text-slate-800 dark:text-slate-200">{e.moduleName}</span>
                <Badge tone={SEVERITY_TONE[e.severity]}>{e.confidence}%</Badge>
              </div>
              <p className="truncate text-slate-500 dark:text-slate-400">
                {e.cameraName} · {e.timestamp}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
