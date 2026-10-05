import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from './Button';
import { cn } from './cn';

export interface ErrorStateProps {
  message?: string | null;
  title?: string;
  onRetry?: () => void;
  /** 'inline' — tor banner (jadval/karta ustida); 'block' — markazdagi katta holat. */
  variant?: 'inline' | 'block';
  className?: string;
}

/** Xato holati: nima bo'ldi + "Qayta urinish". */
export function ErrorState({ message, title = "Ma'lumotni olib bo'lmadi", onRetry, variant = 'inline', className }: ErrorStateProps) {
  if (variant === 'block') {
    return (
      <div role="alert" className={cn('flex flex-col items-center justify-center px-6 py-10 text-center', className)}>
        <div className="mb-2.5 flex h-9 w-9 items-center justify-center rounded-[2px] border border-danger/40 bg-danger-soft text-danger">
          <AlertTriangle size={18} aria-hidden="true" />
        </div>
        <p className="intel-micro intel-micro-wrap !text-[12px] !text-danger">{title}</p>
        {message && <p className="intel-code mt-1.5 max-w-md text-[12px] leading-relaxed text-muted">{message}</p>}
        {onRetry && (
          <Button className="mt-3" icon={RotateCcw} onClick={onRetry}>
            Qayta urinish
          </Button>
        )}
      </div>
    );
  }
  return (
    <div
      role="alert"
      className={cn(
        // Chap chetdagi qalin qizil qirra — xato qaydining belgisi.
        'flex flex-wrap items-start gap-2.5 rounded-card border border-danger/30 border-l-[3px] border-l-danger bg-danger-soft px-3 py-2',
        className,
      )}
    >
      <AlertTriangle size={15} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="intel-micro intel-micro-wrap !text-danger">{title}</p>
        {message && <p className="intel-code mt-0.5 text-[12px] leading-4 text-muted">{message}</p>}
      </div>
      {onRetry && (
        <Button size="sm" icon={RotateCcw} onClick={onRetry}>
          Qayta urinish
        </Button>
      )}
    </div>
  );
}
