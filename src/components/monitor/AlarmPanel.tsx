import { useCallback } from 'react';
import { AlertTriangle, Loader2, LogIn, Siren } from 'lucide-react';
import { api, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useLiveEvents } from '../../lib/realtime';
import { useServerPage } from '../../lib/useServerPage';
import type { AIEvent, CameraFeed } from '../../types';

const PAGE_SIZE = 5;

/** O'ng panelning pastki qismi — eng yuqori muhimlikdagi (severity=yuqori)
 * hodisalarni "signal" sifatida ko'rsatadi. Kamerani bosish uni asosiy
 * ko'rinishga o'tkazadi — avval joriy yuklangan `cameras` ro'yxatidan
 * qidiradi, topilmasa (masalan sahifalash tufayli hozir ro'yxatda yo'q)
 * ochiq public qidiruv orqali bitta martalik so'rov bilan topadi. */
export default function AlarmPanel({
  cameras,
  onSelectCamera,
}: {
  cameras: CameraFeed[];
  onSelectCamera: (camera: CameraFeed) => void;
}) {
  const { token } = useAuth();
  const {
    items: events,
    page,
    loading,
    error,
    reload,
  } = useServerPage<AIEvent>('/api/events', { severity: 'yuqori' }, PAGE_SIZE);

  useLiveEvents(
    (event) => {
      if (page === 1 && event.severity === 'yuqori') reload();
    },
    !!token,
  );

  const handleClick = useCallback(
    async (event: AIEvent) => {
      const known = cameras.find((c) => c.id === event.cameraId);
      if (known) {
        onSelectCamera(known);
        return;
      }
      try {
        const res = await api.get<Page<CameraFeed>>(
          `/api/public/cameras?search=${encodeURIComponent(event.cameraName)}&pageSize=1`,
        );
        if (res.items[0]) onSelectCamera(res.items[0]);
      } catch {
        /* kamera topilmadi — jim o'tkazib yuboriladi, ro'yxat hali ham foydali ma'lumot beradi */
      }
    },
    [cameras, onSelectCamera],
  );

  return (
    <div className="glass p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-sm font-extrabold text-slate-900 dark:text-slate-100">
        <Siren size={15} className="text-red-500" />
        Alarm
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
          Faol signal yo'q
        </p>
      ) : (
        <ul className="space-y-2">
          {events.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => handleClick(e)}
                className="flex w-full items-start gap-2 rounded-lg bg-red-50/80 p-2.5 text-left text-xs transition-colors hover:bg-red-100/80 dark:bg-red-500/10 dark:hover:bg-red-500/15"
              >
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-red-500" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-red-700 dark:text-red-400">{e.cameraName}</p>
                  <p className="truncate text-red-600/80 dark:text-red-400/70">
                    {e.moduleName} · {e.timestamp}
                  </p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
