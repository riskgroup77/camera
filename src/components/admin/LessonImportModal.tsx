import { useState, type FormEvent } from 'react';
import { FileUp, Loader2 } from 'lucide-react';
import Modal from '../Modal';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';

interface ImportResult {
  imported: number;
  skipped: number;
  errors: { row: number; message: string }[];
}

const CSV_TEMPLATE = `date,group,faculty,subject,teacher_id,camera_id,scheduled_start_time
2026-09-01,101-guruh,Davolash ishi,Anatomiya,,,2026-09-01T09:00
`;

export default function LessonImportModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { token } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleClose() {
    setFile(null);
    setResult(null);
    setError(null);
    onClose();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.postForm<ImportResult>('/api/lesson-sessions/import', form, token);
      setResult(res);
      if (res.imported > 0) onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import xatosi');
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Dars jadvali CSV import" maxWidth="max-w-md">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Majburiy ustunlar: <span className="font-mono">date, group, faculty, subject</span>.
          Ixtiyoriy: <span className="font-mono">teacher_id, camera_id, scheduled_start_time</span>.
        </p>

        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 px-4 py-6 dark:border-white/15">
          <FileUp size={22} className="text-indigo-500" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {file ? file.name : 'CSV fayl tanlang'}
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>

        <details className="rounded-xl bg-white/40 px-3 py-2 text-xs dark:bg-white/5">
          <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300">
            Namuna format
          </summary>
          <pre className="mt-2 overflow-x-auto font-mono text-[10px] text-slate-500">{CSV_TEMPLATE}</pre>
        </details>

        {error && (
          <p className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </p>
        )}

        {result && (
          <div className="rounded-xl bg-emerald-50 px-3 py-2 text-xs dark:bg-emerald-500/10">
            <p className="font-semibold text-emerald-700 dark:text-emerald-400">
              {result.imported} ta qo&apos;shildi, {result.skipped} ta o&apos;tkazib yuborildi
            </p>
            {result.errors.length > 0 && (
              <ul className="mt-2 max-h-32 space-y-1 overflow-y-auto text-red-600 dark:text-red-400">
                {result.errors.map((err) => (
                  <li key={`${err.row}-${err.message}`}>
                    Qator {err.row}: {err.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={handleClose} className="btn-glass">
            Yopish
          </button>
          <button
            type="submit"
            disabled={!file || uploading}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {uploading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={14} className="animate-spin" />
                Yuklanmoqda...
              </span>
            ) : (
              'Import qilish'
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
