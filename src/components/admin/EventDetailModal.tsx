import { Check, Circle, User, Video, X } from 'lucide-react';
import Modal from '../Modal';
import Badge from '../Badge';
import type { AIEvent, EventStatus } from '../../types';

const SEVERITY_TONE: Record<AIEvent['severity'], 'green' | 'amber' | 'red'> = {
  past: 'green',
  "o'rta": 'amber',
  yuqori: 'red',
};

const SEVERITY_LABEL: Record<AIEvent['severity'], string> = {
  past: 'Past',
  "o'rta": "O'rta",
  yuqori: 'Yuqori',
};

const STATUS_TONE: Record<EventStatus, 'amber' | 'green' | 'red'> = {
  yangi: 'amber',
  tasdiqlangan: 'green',
  rad_etilgan: 'red',
};

const STATUS_LABEL: Record<EventStatus, string> = {
  yangi: 'Yangi',
  tasdiqlangan: 'Tasdiqlangan',
  rad_etilgan: 'Rad etilgan',
};

export default function EventDetailModal({
  event,
  onClose,
  onReview,
}: {
  event: AIEvent | null;
  onClose: () => void;
  onReview: (id: string, status: EventStatus) => void;
}) {
  return (
    <Modal open={!!event} onClose={onClose} title={event?.moduleName} maxWidth="max-w-lg">
      {event && (
        <div className="space-y-5">
          <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-2xl bg-slate-900">
            <Video size={28} className="text-white/30" />
            <span className="absolute left-3 top-3 flex items-center gap-1 rounded-full bg-black/50 px-2.5 py-1 text-xs font-bold text-white">
              <Circle size={6} className="fill-red-500 text-red-500" />
              Hodisa klipi (mock)
            </span>
            <span className="absolute bottom-3 right-3 rounded bg-black/50 px-2 py-1 font-mono text-xs text-white">
              {event.timestamp}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={SEVERITY_TONE[event.severity]}>{`Muhimlik: ${SEVERITY_LABEL[event.severity]}`}</Badge>
            <Badge tone={STATUS_TONE[event.status]}>{STATUS_LABEL[event.status]}</Badge>
            <Badge tone="indigo">{`Ishonch: ${event.confidence}%`}</Badge>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Kamera</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">{event.cameraName}</p>
            </div>
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Joylashuv</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">{event.building}</p>
            </div>
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Kriteriya kodi</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">№{event.moduleCode}</p>
            </div>
            {event.personName && (
              <div className="glass-deep flex items-center gap-2 px-3 py-2.5">
                <User size={14} className="text-slate-400" />
                <div>
                  <p className="text-[11px] text-slate-400 dark:text-slate-500">Shaxs</p>
                  <p className="font-medium text-slate-800 dark:text-slate-200">{event.personName}</p>
                </div>
              </div>
            )}
            {event.reviewedBy && (
              <div className="glass-deep px-3 py-2.5">
                <p className="text-[11px] text-slate-400 dark:text-slate-500">Ko'rib chiqdi</p>
                <p className="font-medium text-slate-800 dark:text-slate-200">{event.reviewedBy}</p>
              </div>
            )}
          </div>

          {event.status === 'yangi' && (
            <div className="rounded-xl bg-indigo-50 p-3 text-xs text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
              AI signal — bu "dalil" emas, "ko'rsatkich". Yakuniy qarorni videoni ko'rib chiqqan
              holda inson qabul qiladi (human-in-the-loop).
            </div>
          )}

          {event.status === 'yangi' && (
            <div className="flex justify-end gap-2">
              <button
                onClick={() => onReview(event.id, 'rad_etilgan')}
                className="flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-600 transition-colors hover:bg-red-100 dark:border-red-900/50 dark:bg-red-950/40 dark:hover:bg-red-950/60"
              >
                <X size={14} />
                Rad etish
              </button>
              <button
                onClick={() => onReview(event.id, 'tasdiqlangan')}
                className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-emerald-700"
              >
                <Check size={14} />
                Tasdiqlash
              </button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
