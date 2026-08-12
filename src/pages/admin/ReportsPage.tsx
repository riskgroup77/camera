import { useState } from 'react';
import {
  Bot,
  Calendar,
  FileSpreadsheet,
  FileText,
  Loader2,
  Sparkles,
  Trash2,
} from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import ConfirmDialog from '../../components/ConfirmDialog';
import ReportDetailModal from '../../components/admin/ReportDetailModal';
import { exportReportAsCsv, exportReportAsPdf } from '../../lib/reportExport';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { useServerPage } from '../../lib/useServerPage';
import type { Report } from '../../types';

const PERIOD_FILTERS = ['Barchasi', 'Kunlik', 'Haftalik', 'Oylik'] as const;
const GENERATE_PERIODS = ['Kunlik', 'Haftalik', 'Oylik'] as const;

export default function ReportsPage() {
  const { token } = useAuth();
  const [filter, setFilter] = useState<(typeof PERIOD_FILTERS)[number]>('Barchasi');
  const [generatePeriod, setGeneratePeriod] = useState<(typeof GENERATE_PERIODS)[number]>('Kunlik');
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Report | null>(null);
  const [deleting, setDeleting] = useState<Report | null>(null);
  const { role } = useAuth();
  const { can } = usePermissions();
  const canExport = can('exportData', role);

  const {
    items: reports,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
    reload,
  } = useServerPage<Report>('/api/reports', { period: filter === 'Barchasi' ? undefined : filter }, 10);

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await api.post<Report>('/api/reports/generate', { period: generatePeriod }, token);
      reload();
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
    } finally {
      setGenerating(false);
    }
  }

  async function handleDelete() {
    if (!deleting) return;
    await api.del(`/api/reports/${deleting.id}`, token);
    setDeleting(null);
    reload();
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Hisobotlar"
        subtitle="Avtomatik generatsiya qilingan kunlik/haftalik/oylik xulosalar (qoidaga asoslangan tahlil)"
        action={
          <div className="flex items-center gap-2">
            <select
              value={generatePeriod}
              onChange={(e) => setGeneratePeriod(e.target.value as (typeof GENERATE_PERIODS)[number])}
              className="rounded-xl border border-white/80 bg-white/60 px-3 py-2 text-sm outline-none dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
            >
              {GENERATE_PERIODS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {generating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              {generating ? 'Generatsiya qilinmoqda...' : 'Yangi hisobot generatsiya qilish'}
            </button>
          </div>
        }
      />

      {generateError && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {generateError}
        </p>
      )}
      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        {PERIOD_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              filter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {loading && reports.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map((r) => (
            <div key={r.id} className="glass-deep p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <Badge tone="indigo">{r.period}</Badge>
                    <Badge tone={r.source === 'llm' ? 'green' : 'slate'}>
                      {r.source === 'llm' ? (
                        <span className="flex items-center gap-1">
                          <Bot size={11} />
                          LLM
                        </span>
                      ) : (
                        'Rule-based'
                      )}
                    </Badge>
                    <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                      <Calendar size={11} />
                      {r.periodLabel}
                    </span>
                  </div>
                  <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">{r.summary}</p>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <button
                    onClick={() => setSelected(r)}
                    className="btn-glass text-xs"
                  >
                    Ko'rish
                  </button>
                  <button
                    onClick={() => exportReportAsCsv(r)}
                    disabled={!canExport}
                    title={canExport ? 'Excel (CSV)' : "Eksport huquqi yo'q"}
                    className="rounded-lg p-2 text-slate-500 dark:text-slate-400 transition-colors hover:bg-white/70 dark:hover:bg-white/10 hover:text-indigo-600 dark:hover:text-indigo-400 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-500"
                  >
                    <FileSpreadsheet size={16} />
                  </button>
                  <button
                    onClick={() => exportReportAsPdf(r)}
                    disabled={!canExport}
                    title={canExport ? 'PDF' : "Eksport huquqi yo'q"}
                    className="rounded-lg p-2 text-slate-500 dark:text-slate-400 transition-colors hover:bg-white/70 dark:hover:bg-white/10 hover:text-indigo-600 dark:hover:text-indigo-400 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-500"
                  >
                    <FileText size={16} />
                  </button>
                  <button
                    onClick={() => setDeleting(r)}
                    title="O'chirish"
                    className="rounded-lg p-2 text-slate-500 dark:text-slate-400 transition-colors hover:bg-white/70 dark:hover:bg-white/10 hover:text-red-600 dark:hover:text-red-400"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2 border-t border-white/70 dark:border-white/10 pt-3">
                {r.stats.map((s) => (
                  <span
                    key={s.label}
                    className="rounded-lg bg-white/70 dark:bg-white/10 px-2.5 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-400"
                  >
                    {s.label}: <span className="font-bold text-slate-900 dark:text-slate-100">{s.value}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}

          {reports.length === 0 && (
            <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
              Bu davr uchun hisobot topilmadi
            </p>
          )}

          <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
        </div>
      )}

      <ReportDetailModal report={selected} onClose={() => setSelected(null)} />
      <ConfirmDialog
        open={!!deleting}
        title="Hisobotni o'chirish"
        message={deleting ? `"${deleting.periodLabel}" hisobotini o'chirishni tasdiqlaysizmi? Bu amalni ortga qaytarib bo'lmaydi.` : ''}
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </section>
  );
}
