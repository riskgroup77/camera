import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import Modal from './Modal';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "O'chirish",
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bitta ConfirmDialog instansi sahifa umrida qayta-qayta ochiladi
  // (masalan Hodisalar jurnalida har bir qatorning o'z "O'chirish"
  // tugmasi bir xil dialogni ochadi) — `pending`/`error` shu instansining
  // ICHKI holati bo'lgani uchun, ochilish/yopilish orasida o'zi
  // tozalanmasdi: birinchi o'chirishdan qolgan `pending=true` ikkinchi
  // ochilishda ham qolib, tasdiqlash tugmasini "O'chirilmoqda..." holida
  // abadiy o'chirilgan (disabled) qilib qo'yardi — go'yo hali ham
  // birinchisi o'chirilayotgandek. Har safar YANGI ochilganda (open
  // false->true) holatni tozalab qo'yamiz.
  useEffect(() => {
    if (open) {
      setPending(false);
      setError(null);
    }
  }, [open]);

  async function handleConfirm() {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
      setPending(false);
    }
  }

  return (
    <Modal open={open} onClose={onCancel} maxWidth="max-w-sm">
      <div className="flex flex-col items-center gap-3 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400">
          <AlertTriangle size={22} />
        </div>
        <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">{title}</h3>
        <p className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
        {error && (
          <p className="w-full rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </p>
        )}
        <div className="mt-2 flex w-full justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={pending} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={pending}
            className="flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {pending && <Loader2 size={14} className="animate-spin" />}
            {pending ? "O'chirilmoqda..." : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
