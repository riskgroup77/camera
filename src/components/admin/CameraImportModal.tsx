import { useState, type FormEvent } from 'react';
import { FileUp, Loader2 } from 'lucide-react';
import Modal from '../Modal';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';

interface ImportResult {
  imported: number;
  skipped: number;
  skippedRecorders: number;
  errors: { row: number; message: string }[];
}

export default function CameraImportModal({
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
      const res = await api.postForm<ImportResult>('/api/cameras/import', form, token);
      setResult(res);
      if (res.imported > 0) onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import xatosi');
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="SADP'dan kameralarni import qilish" maxWidth="max-w-md">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Hikvision SADP dasturidagi <span className="font-semibold">Export</span> tugmasi bilan olingan
          CSV fayl. Faqat <span className="font-mono">Active</span> holatdagi qurilmalar qo&apos;shiladi,
          NVR/DVR qurilmalar avtomatik o&apos;tkazib yuboriladi. Qo&apos;shilgan kameralar
          &quot;Tasniflanmagan&quot; xona bilan, nofaol holatda qo&apos;shiladi — bino/xonasini keyin
          har birida qo&apos;lda belgilashingiz kerak bo&apos;ladi.
        </p>

        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 px-4 py-6 dark:border-white/15">
          <FileUp size={22} className="text-indigo-500" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {file ? file.name : 'SADP CSV fayl tanlang'}
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {error && (
          <p className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </p>
        )}

        {result && (
          <div className="rounded-xl bg-emerald-50 px-3 py-2 text-xs dark:bg-emerald-500/10">
            <p className="font-semibold text-emerald-700 dark:text-emerald-400">
              {result.imported} ta qo&apos;shildi, {result.skipped} ta o&apos;tkazib yuborildi
              {result.skippedRecorders > 0 && `, ${result.skippedRecorders} ta recorder (NVR/DVR) o'tkazib yuborildi`}
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
