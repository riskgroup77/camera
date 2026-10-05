import { useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, HelpCircle } from 'lucide-react';
import { Button } from './Button';
import { cn } from './cn';
import { Modal } from './Modal';

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 'danger' — o'chirish kabi qaytarib bo'lmaydigan harakat. */
  tone?: 'danger' | 'primary';
  onCancel: () => void;
  /** Promise qaytarsa — tugma kutadi; xato bo'lsa dialog ichida ko'rsatiladi. */
  onConfirm: () => Promise<void> | void;
}

/** Tasdiqlash dialogi. Xato bo'lsa yopilmaydi va sababni ko'rsatadi. */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Tasdiqlash',
  cancelLabel = 'Bekor qilish',
  tone = 'danger',
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bir instansiya qayta-qayta ochiladi — har ochilishda holat tozalanadi.
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
    } finally {
      setPending(false);
    }
  }

  const Icon = tone === 'danger' ? AlertTriangle : HelpCircle;

  return (
    <Modal
      open={open}
      onClose={pending ? () => {} : onCancel}
      size="sm"
      ariaLabel={title}
      dismissible={!pending}
      footer={
        <>
          {/* Xavfli harakatda fokus "Bekor qilish"da — tasodifiy Enter o'chirib yubormasin. */}
          <Button onClick={onCancel} disabled={pending} data-autofocus={tone === 'danger' ? true : undefined}>
            {cancelLabel}
          </Button>
          <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={handleConfirm} loading={pending} data-autofocus={tone === 'danger' ? undefined : true}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex gap-3">
        <div
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-[2px] border',
            tone === 'danger' ? 'border-danger/40 bg-danger-soft text-danger' : 'border-primary/30 bg-primary-soft text-primary',
          )}
        >
          <Icon size={16} aria-hidden="true" />
        </div>
        <div className="min-w-0">
          {/* Savolning o'zi — proza: odam o'qiydigan gap, bosh harfga aylanmaydi. */}
          <h2 className="text-[14px] font-semibold leading-5 text-fg">{title}</h2>
          {message && <div className="mt-1 text-[13px] leading-5 text-muted">{message}</div>}
          {error && (
            <p role="alert" className="intel-code mt-2.5 rounded-control border border-danger/30 border-l-[3px] border-l-danger bg-danger-soft px-2.5 py-1.5 text-[12px] font-medium text-danger">
              {error}
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
