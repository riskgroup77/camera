import { useState } from 'react';
import { FileText, Loader2, Sparkles } from 'lucide-react';
import { exportReportAsPdf } from '../../lib/reportExport';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Report } from '../../types';

const PERIODS = ['Kunlik', 'Haftalik', 'Oylik'] as const;

/** O'ng panelning yuqori qismi — kunlik/haftalik/oylik hisobotni bir
 * tugma bosishda generatsiya qilib, darhol PDF qilib yuklab olish. */
export default function ReportPanel() {
  const { token } = useAuth();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>('Kunlik');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastReport, setLastReport] = useState<Report | null>(null);

  async function handleGenerateAndDownload() {
    if (!token) {
      setError('Hisobot olish uchun tizimga kiring');
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const report = await api.post<Report>('/api/reports/generate', { period }, token);
      setLastReport(report);
      exportReportAsPdf(report);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tarmoq xatosi — hisobot olinmadi");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="glass p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-sm font-extrabold text-slate-900 dark:text-slate-100">
        <FileText size={15} className="text-indigo-500" />
        Hisobot
      </h3>

      <div className="mb-3 grid grid-cols-3 gap-1.5">
        {PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPeriod(p)}
            className={`rounded-lg px-2 py-1.5 text-[11px] font-semibold transition-colors ${
              period === p
                ? 'bg-indigo-600 text-white'
                : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={handleGenerateAndDownload}
        disabled={generating}
        className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {generating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {generating ? 'Tayyorlanmoqda...' : `${period} hisobotni PDF qilib yuklash`}
      </button>

      {error && <p className="mt-2 text-[11px] font-medium text-red-600 dark:text-red-400">{error}</p>}

      {lastReport && !error && (
        <p className="mt-2 truncate text-[11px] text-slate-500 dark:text-slate-400">
          Oxirgi: {lastReport.periodLabel} · {lastReport.generatedAt}
        </p>
      )}
    </div>
  );
}
