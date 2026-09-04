import { useState } from 'react';
import { Eye, ListChecks, Loader2, LogIn } from 'lucide-react';
import Badge from '../Badge';
import EventDetailModal from '../admin/EventDetailModal';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useLiveEvents } from '../../lib/realtime';
import { useServerPage } from '../../lib/useServerPage';
import type { AIEvent, EventStatus } from '../../types';

const SEVERITY_TONE: Record<AIEvent['severity'], 'green' | 'amber' | 'red'> = {
  past: 'green',
  "o'rta": 'amber',
  yuqori: 'red',
};

const PAGE_SIZE = 6;

/** Devor jurnali KO'RSATMAYDIGAN modullar.
 *
 * #25 ("Hovlida transport harakati") — modul o'z ta'rifida yozilganidek,
 * qaysi kamera hovliga qaraganini bilmaydi va barcha kameralarda
 * ishlaydi. Tekshirilgan namunasi ichkaridagi laboratoriya edi. Modul
 * o'chirilmagan — hodisalari bazada va Hodisalar sahifasida qoladi,
 * faqat operator kuzatib turadigan bu ro'yxatga chiqmaydi. */
const HIDDEN_MODULE_CODES = [25];

/** O'ng panelning o'rta qismi — devorda ko'rsatiladigan hodisalar.
 *
 * Faqat operator TASDIQLAGAN hodisalar chiqadi. Bu ataylab: modullarning
 * bir qismi hali ishonchli emas (o'lchangan holatlar — bo'sh xonadagi
 * "tartib buzilishi", 28 piksellik yuzda "uxlab qolish"), va devor
 * institutda ko'rsatiladigan joy. Tasdiqlanmagan signal shovqin bo'lishi
 * mumkin, tasdiqlangani esa odam ko'rib chiqqan dalil.
 *
 * To'liq oqim — tasdiqlanmaganlar ham — Hodisalar sahifasida qoladi:
 * operator aynan o'sha yerda ko'rib chiqadi va tasdiqlaydi. */
export default function EventsLogPanel() {
  const { token } = useAuth();
  const [selected, setSelected] = useState<AIEvent | null>(null);
  const { items: events, page, loading, error, reload } = useServerPage<AIEvent>(
    '/api/events',
    { excludeModules: HIDDEN_MODULE_CODES.join(','), status: 'tasdiqlangan' },
    PAGE_SIZE,
  );

  useLiveEvents(() => {
    if (page === 1) reload();
  }, !!token);

  // Bu yerdan ham tasdiqlash/rad etish mumkin: devorni kuzatib turgan
  // operator hodisani ko'rib, o'sha zahoti hukm qila oladi.
  async function review(id: string, status: EventStatus) {
    try {
      await api.patch(`/api/events/${id}/review`, { status }, token);
    } finally {
      setSelected(null);
      reload();
    }
  }

  return (
    <div className="glass p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-sm font-extrabold text-slate-900 dark:text-slate-100">
        <ListChecks size={15} className="text-indigo-500" />
        Hodisalar jurnali
      </h3>

      {!token ? (
        <p className="flex items-center gap-1.5 rounded-lg bg-white/60 px-3 py-2.5 text-xs text-slate-500 dark:bg-white/5 dark:text-slate-400">
          <LogIn size={13} />
          Ko&apos;rish uchun tizimga kiring
        </p>
      ) : loading && events.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-slate-400">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : error ? (
        <p className="text-[11px] font-medium text-red-600 dark:text-red-400">{error}</p>
      ) : events.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-[11px] leading-relaxed text-slate-400 dark:border-white/10 dark:text-slate-500">
          Tasdiqlangan hodisa yo&apos;q.
          <br />
          Yangi signallar Hodisalar sahifasida ko&apos;rib chiqiladi.
        </p>
      ) : (
        <ul className="space-y-2">
          {events.map((e) => (
            <li key={e.id} className="rounded-lg bg-white/60 p-2.5 text-xs dark:bg-white/5">
              <div className="mb-0.5 flex items-center justify-between gap-2">
                <span className="truncate font-semibold text-slate-800 dark:text-slate-200">{e.moduleName}</span>
                <Badge tone={SEVERITY_TONE[e.severity]}>{e.confidence}%</Badge>
              </div>
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-slate-500 dark:text-slate-400">
                  {e.cameraName} · {e.timestamp}
                </p>
                <button
                  type="button"
                  onClick={() => setSelected(e)}
                  className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-indigo-600 transition-colors hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-500/10"
                >
                  <Eye size={12} />
                  Ko&apos;rish
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Hodisalar sahifasidagi bilan AYNAN bir xil oyna — dalil rasm,
          kamera, vaqt va tasdiqlash tugmalari. Alohida nusxa yozish
          ikkalasining vaqt o'tib bir-biridan farq qilishiga olib
          kelardi. */}
      <EventDetailModal event={selected} onClose={() => setSelected(null)} onReview={review} />
    </div>
  );
}
