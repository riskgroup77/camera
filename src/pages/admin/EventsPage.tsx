import { useEffect, useState } from 'react';
import { AlertOctagon, Check, Clock3, Loader2, Search, Trash2, X } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import ConfirmDialog from '../../components/ConfirmDialog';
import EventDetailModal from '../../components/admin/EventDetailModal';
import { ApiError, api, buildQuery, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useLiveEvents } from '../../lib/realtime';
import { useServerPage } from '../../lib/useServerPage';
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

const SEVERITY_FILTERS = ['Barchasi', 'Past', "O'rta", 'Yuqori'] as const;
const SEVERITY_VALUE: Record<(typeof SEVERITY_FILTERS)[number], AIEvent['severity'] | undefined> = {
  Barchasi: undefined,
  Past: 'past',
  "O'rta": "o'rta",
  Yuqori: 'yuqori',
};
const STATUS_FILTERS = ['Barchasi', 'Yangi', 'Tasdiqlangan', 'Rad etilgan'] as const;
const STATUS_VALUE: Record<(typeof STATUS_FILTERS)[number], EventStatus | undefined> = {
  Barchasi: undefined,
  Yangi: 'yangi',
  Tasdiqlangan: 'tasdiqlangan',
  'Rad etilgan': 'rad_etilgan',
};

export default function EventsPage() {
  const { token } = useAuth();
  const [severityFilter, setSeverityFilter] = useState<(typeof SEVERITY_FILTERS)[number]>('Barchasi');
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>('Barchasi');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<AIEvent | null>(null);
  const [deleting, setDeleting] = useState<AIEvent | null>(null);
  const [counts, setCounts] = useState<{ total: number; yangi: number; tasdiqlangan: number; rad_etilgan: number } | null>(
    null,
  );

  const {
    items: events,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
    reload,
  } = useServerPage<AIEvent>(
    '/api/events',
    {
      severity: SEVERITY_VALUE[severityFilter],
      status: STATUS_VALUE[statusFilter],
      search: search.trim() || undefined,
    },
    10,
  );

  // Yangi hodisa real WebSocket orqali kelganda (backend POST /api/events yoki
  // PATCH /review'da broadcast qiladi) — 1-sahifadagi ro'yxatni yangilaymiz,
  // shunda yangi/yangilangan yozuv joriy filtrlarga mos bo'lsa darhol ko'rinadi.
  useLiveEvents(() => {
    if (page === 1) reload();
  });

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all(
      (['yangi', 'tasdiqlangan', 'rad_etilgan'] as const).map((s) =>
        api.get<Page<AIEvent>>(`/api/events${buildQuery({ status: s, pageSize: 1 })}`, token),
      ),
    ).then(([yangi, tasdiqlangan, rad_etilgan]) => {
      if (cancelled) return;
      setCounts({
        total: yangi.total + tasdiqlangan.total + rad_etilgan.total,
        yangi: yangi.total,
        tasdiqlangan: tasdiqlangan.total,
        rad_etilgan: rad_etilgan.total,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [token, events]);

  async function handleDelete() {
    if (!deleting) return;
    await api.del(`/api/events/${deleting.id}`, token);
    setDeleting(null);
    reload();
  }

  async function handleReview(id: string, status: EventStatus) {
    try {
      const updated = await api.patch<AIEvent>(`/api/events/${id}/review`, { status }, token);
      setSelected((cur) => (cur && cur.id === id ? updated : cur));
      reload();
    } catch (err) {
      // Modal darajasida ko'rsatiladigan alohida xato holati yo'q — konsolga yozamiz.
      console.error(err instanceof ApiError ? err.message : err);
    }
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Hodisalar jurnali"
        subtitle="AI aniqlagan hodisalar — inson tomonidan tasdiqlash (human-in-the-loop)"
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard icon={<AlertOctagon size={20} />} value={counts?.total ?? '—'} label="Jami hodisalar" tone="indigo" />
        <StatCard icon={<Clock3 size={20} />} value={counts?.yangi ?? '—'} label="Kutilmoqda" tone="amber" />
        <StatCard icon={<Check size={20} />} value={counts?.tasdiqlangan ?? '—'} label="Tasdiqlangan" tone="green" />
        <StatCard icon={<X size={20} />} value={counts?.rad_etilgan ?? '—'} label="Rad etilgan" tone="red" />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Kriteriya bo'yicha qidiruv..."
            aria-label="Hodisalarni qidirish"
            className="w-full rounded-xl border border-white/80 bg-white/60 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
          />
        </div>

        <div className="flex flex-wrap gap-2 text-sm">
          {SEVERITY_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setSeverityFilter(f)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                severityFilter === f
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
              }`}
            >
              {f}
            </button>
          ))}
          <span className="mx-1 w-px self-stretch bg-white/80 dark:bg-white/10" />
          {STATUS_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                statusFilter === f
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      {loading && events.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : events.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-400 dark:border-white/10 dark:text-slate-500">
          Filtrlarga mos hodisa topilmadi
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-white/5 dark:text-slate-400">
                <th className="px-4 py-3">Vaqt</th>
                <th className="px-4 py-3">Kriteriya</th>
                <th className="px-4 py-3">Kamera / Bino</th>
                <th className="px-4 py-3">Ishonch</th>
                <th className="px-4 py-3">Muhimlik</th>
                <th className="px-4 py-3">Holat</th>
                <th className="px-4 py-3">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {events.map((e) => (
                <tr key={e.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                    {e.timestamp}
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{e.moduleName}</p>
                    {e.personName && (
                      <p className="text-xs text-slate-500 dark:text-slate-400">{e.personName}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {e.cameraName}
                    <p className="text-xs text-slate-400 dark:text-slate-500">{e.building}</p>
                  </td>
                  <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">{e.confidence}%</td>
                  <td className="px-4 py-3">
                    <Badge tone={SEVERITY_TONE[e.severity]}>{SEVERITY_LABEL[e.severity]}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[e.status]}>{STATUS_LABEL[e.status]}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setSelected(e)}
                        className="text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        Ko'rish
                      </button>
                      <button
                        onClick={() => setDeleting(e)}
                        title="O'chirish"
                        className="text-slate-400 transition-colors hover:text-red-600 dark:text-slate-500 dark:hover:text-red-400"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
          </div>
        </div>
      )}

      <EventDetailModal event={selected} onClose={() => setSelected(null)} onReview={handleReview} />
      <ConfirmDialog
        open={!!deleting}
        title="Hodisani o'chirish"
        message={deleting ? `"${deleting.moduleName}" hodisasini o'chirishni tasdiqlaysizmi? Bu amalni ortga qaytarib bo'lmaydi.` : ''}
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </section>
  );
}
