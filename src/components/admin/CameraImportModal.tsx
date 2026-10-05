import { useState, type FormEvent } from 'react';
import { FileUp } from 'lucide-react';
import { Notice } from '../settings/kit';
import { Button, Modal, cn } from '../../ui';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';

interface ImportResult {
  imported: number;
  skipped: number;
  skippedRecorders: number;
  errors: { row: number; message: string }[];
}

/** Fayl tanlash maydoni (butun maydon bosiladi, klaviatura bilan ham). */
export function CsvDropzone({ file, placeholder, onChange }: { file: File | null; placeholder: string; onChange: (file: File | null) => void }) {
  return (
    <label
      className={cn(
        'flex cursor-pointer flex-col items-center gap-2 border border-dashed px-4 py-6 text-center transition-colors hover:border-primary/60 hover:bg-primary-soft/40',
        'has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-primary/40',
        file ? 'border-primary/50 bg-primary-soft/40' : 'border-border-strong bg-surface-2',
      )}
    >
      <FileUp size={22} className="text-primary" aria-hidden="true" />
      <span className="text-sm font-medium text-fg">{file ? file.name : placeholder}</span>
      {file && <span className="text-xs text-muted">Boshqa fayl tanlash uchun bosing</span>}
      <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => onChange(e.target.files?.[0] ?? null)} />
    </label>
  );
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
    <Modal
      open={open}
      onClose={handleClose}
      title="SADP'dan kameralarni import qilish"
      description="SADP eksport qilgan CSV fayl."
      size="md"
      dismissible={!uploading}
      footer={
        <>
          <Button onClick={handleClose} disabled={uploading}>
            Yopish
          </Button>
          <Button type="submit" form="camera-import-form" variant="primary" icon={FileUp} loading={uploading} disabled={!file}>
            Import qilish
          </Button>
        </>
      }
    >
      <form id="camera-import-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Notice tone="info">
          SADP dasturidagi <span className="font-semibold">Export</span> tugmasi bilan olingan CSV fayl. Faqat{' '}
          <span className="font-mono">Active</span> holatdagi qurilmalar qo&apos;shiladi, NVR/DVR qurilmalar avtomatik
          o&apos;tkazib yuboriladi. Qo&apos;shilgan kameralar «Tasniflanmagan» xona bilan, nofaol holatda qo&apos;shiladi —
          bino/xonasini keyin har birida qo&apos;lda belgilashingiz kerak bo&apos;ladi.
        </Notice>

        <CsvDropzone file={file} placeholder="SADP CSV fayl tanlang" onChange={setFile} />

        {error && <Notice tone="danger">{error}</Notice>}

        {result && (
          <Notice
            tone={result.errors.length > 0 ? 'warning' : 'success'}
            title={
              `${result.imported} ta qo'shildi, ${result.skipped} ta o'tkazib yuborildi` +
              (result.skippedRecorders > 0 ? `, ${result.skippedRecorders} ta recorder (NVR/DVR) o'tkazib yuborildi` : '')
            }
          >
            {result.errors.length > 0 && (
              <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto text-danger">
                {result.errors.map((err) => (
                  <li key={`${err.row}-${err.message}`}>
                    Qator {err.row}: {err.message}
                  </li>
                ))}
              </ul>
            )}
          </Notice>
        )}
      </form>
    </Modal>
  );
}
