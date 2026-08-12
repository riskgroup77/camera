import { Download, FileSpreadsheet, FileText } from 'lucide-react';
import Modal from '../Modal';
import Badge from '../Badge';
import { exportReportAsCsv, exportReportAsPdf } from '../../lib/reportExport';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import type { Report } from '../../types';

export default function ReportDetailModal({
  report,
  onClose,
}: {
  report: Report | null;
  onClose: () => void;
}) {
  const { role } = useAuth();
  const { can } = usePermissions();
  const canExport = can('exportData', role);

  return (
    <Modal open={!!report} onClose={onClose} title={report?.periodLabel} maxWidth="max-w-2xl">
      {report && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="indigo">{report.period}</Badge>
            <Badge tone={report.source === 'llm' ? 'green' : 'slate'}>
              {report.source === 'llm' ? 'Claude API (LLM)' : 'Qoida-asosida'}
            </Badge>
            <span className="text-xs text-slate-400 dark:text-slate-500">Generatsiya: {report.generatedAt}</span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {report.stats.map((s) => (
              <div key={s.label} className="glass-deep px-3 py-2.5 text-center">
                <p className="text-base font-extrabold text-slate-900 dark:text-slate-100">{s.value}</p>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">{s.label}</p>
              </div>
            ))}
          </div>

          <div className="glass-deep p-4">
            <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700 dark:text-slate-300">
              {report.body}
            </p>
          </div>

          <div className="flex items-center justify-end gap-2">
            {!canExport && (
              <span className="text-[11px] text-slate-400 dark:text-slate-500">Eksport huquqi yo'q</span>
            )}
            <button
              onClick={() => exportReportAsCsv(report)}
              disabled={!canExport}
              className="btn-glass flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <FileSpreadsheet size={14} />
              Excel (CSV)
            </button>
            <button
              onClick={() => exportReportAsPdf(report)}
              disabled={!canExport}
              className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <FileText size={14} />
              <Download size={14} />
              PDF yuklab olish
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
