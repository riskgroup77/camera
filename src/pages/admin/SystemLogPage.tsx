import { useEffect, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import { exportRowsAsCsv } from '../../lib/csvExport';
import { api, buildQuery, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { useServerPage } from '../../lib/useServerPage';
import type { AuditLogEntry } from '../../types';
import { CheckCircle2, AlertCircle, AlertTriangle } from 'lucide-react';

const STATUS_TONE: Record<AuditLogEntry['status'], 'green' | 'red' | 'amber'> = {
  muvaffaqiyatli: 'green',
  xatolik: 'red',
  ogohlantirish: 'amber',
};

const STATUS_LABEL: Record<AuditLogEntry['status'], string> = {
  muvaffaqiyatli: 'Muvaffaqiyatli',
  xatolik: 'Xatolik',
  ogohlantirish: 'Ogohlantirish',
};

const STATUS_FILTERS = ['Barchasi', 'Muvaffaqiyatli', 'Xatolik', 'Ogohlantirish'] as const;
const STATUS_VALUE: Record<(typeof STATUS_FILTERS)[number], AuditLogEntry['status'] | undefined> = {
  Barchasi: undefined,
  Muvaffaqiyatli: 'muvaffaqiyatli',
  Xatolik: 'xatolik',
  Ogohlantirish: 'ogohlantirish',
};
const MODULE_FILTERS = ['Autentifikatsiya', 'Kameralar', 'Talabalar', 'AI Modullari', 'Tashkilot'] as const;

export default function SystemLogPage() {
  const { role, token } = useAuth();
  const { can } = usePermissions();
  const canExport = can('exportData', role);

  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>('Barchasi');
  const [moduleFilter, setModuleFilter] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ muvaffaqiyatli: number; xatolik: number; ogohlantirish: number } | null>(
    null,
  );
  const [exporting, setExporting] = useState(false);

  const {
    items: entries,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
  } = useServerPage<AuditLogEntry>(
    '/api/audit-log',
    { status: STATUS_VALUE[statusFilter], module: moduleFilter ?? undefined },
    15,
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all(
      (['muvaffaqiyatli', 'xatolik', 'ogohlantirish'] as const).map((s) =>
        api.get<Page<AuditLogEntry>>(`/api/audit-log${buildQuery({ status: s, pageSize: 1 })}`, token),
      ),
    ).then(([ok, err, warn]) => {
      if (cancelled) return;
      setCounts({ muvaffaqiyatli: ok.total, xatolik: err.total, ogohlantirish: warn.total });
    });
    return () => {
      cancelled = true;
    };
  }, [token, entries]);

  async function handleExport() {
    setExporting(true);
    try {
      const EXPORT_PAGE_SIZE = 500;
      const all: AuditLogEntry[] = [];
      let currentPage = 1;
      let totalPages = 1;
      do {
        const qs = buildQuery({
          status: STATUS_VALUE[statusFilter],
          module: moduleFilter ?? undefined,
          page: currentPage,
          pageSize: EXPORT_PAGE_SIZE,
        });
        const res = await api.get<Page<AuditLogEntry>>(`/api/audit-log${qs}`, token);
        all.push(...res.items);
        totalPages = res.totalPages;
        currentPage += 1;
      } while (currentPage <= totalPages);

      exportRowsAsCsv(
        ['Vaqt', 'Foydalanuvchi', 'Amal', 'Modul', 'Holat', 'IP manzil'],
        all.map((l) => [l.timestamp, l.user, l.action, l.module, STATUS_LABEL[l.status], l.ip]),
        `tizim-jurnali-${new Date().toISOString().slice(0, 10)}.csv`,
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Tizim jurnali"
        subtitle="Barcha tizim harakatlari va audit yozuvlari"
        action={
          canExport ? (
            <button
              onClick={handleExport}
              disabled={exporting}
              className="btn-glass flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              CSV yuklab olish
            </button>
          ) : (
            <span
              title="Eksport huquqi yo'q — Foydalanuvchilar va Rollar bo'limida yoqish mumkin"
              className="flex cursor-not-allowed items-center gap-1.5 rounded-xl border border-white/[.88] bg-white/30 px-3 py-2 text-[12.5px] font-semibold text-slate-400 dark:border-white/10 dark:bg-white/5 dark:text-slate-500"
            >
              <Download size={14} />
              CSV yuklab olish
            </span>
          )
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard icon={<CheckCircle2 size={20} />} value={counts?.muvaffaqiyatli ?? '—'} label="Muvaffaqiyatli" tone="green" />
        <StatCard icon={<AlertCircle size={20} />} value={counts?.xatolik ?? '—'} label="Xatoliklar" tone="red" />
        <StatCard icon={<AlertTriangle size={20} />} value={counts?.ogohlantirish ?? '—'} label="Ogohlantirishlar" tone="amber" />
      </div>

      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              statusFilter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
            }`}
          >
            {f}
          </button>
        ))}
        <span className="mx-1 w-px self-stretch bg-white/80 dark:bg-white/10" />
        {MODULE_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setModuleFilter((cur) => (cur === f ? null : f))}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              moduleFilter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      {loading && entries.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
          Filtrlarga mos yozuv topilmadi
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <th className="px-4 py-3">Vaqt</th>
                <th className="px-4 py-3">Foydalanuvchi</th>
                <th className="px-4 py-3">Amal</th>
                <th className="px-4 py-3">Modul</th>
                <th className="px-4 py-3">Holat</th>
                <th className="px-4 py-3">IP manzil</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {entries.map((l) => (
                <tr key={l.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                    {l.timestamp}
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">{l.user}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{l.action}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{l.module}</td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[l.status]}>{STATUS_LABEL[l.status]}</Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500 dark:text-slate-400">{l.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
          </div>
        </div>
      )}
    </section>
  );
}
