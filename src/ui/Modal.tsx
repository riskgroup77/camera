import { useId, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from './cn';
import { IconButton } from './IconButton';
import { useDialog } from './internal/useDialog';

const SIZE = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
  xl: 'sm:max-w-4xl',
} as const;

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Pastki tugmalar (o'ngga tekislanadi). */
  footer?: ReactNode;
  size?: keyof typeof SIZE;
  /** Fonni bosganda yopilmasin (masalan, saqlanmagan forma). */
  dismissible?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Sarlavhasiz dialog uchun ekran o'quvchi nomi. */
  ariaLabel?: string;
  className?: string;
}

/** Markazdagi dialog — asosan formalar uchun. Tafsilotlarni ko'rish uchun Drawer. */
export function Modal({ open, onClose, title, description, children, footer, size = 'md', dismissible = true, initialFocusRef, ariaLabel, className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useDialog(open, onClose, panelRef, initialFocusRef);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 animate-fade-in bg-black/45" onClick={dismissible ? onClose : undefined} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : ariaLabel}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          'relative flex max-h-[92vh] w-full animate-pop-in flex-col rounded-card border border-border-strong bg-surface text-fg shadow-pop outline-none',
          SIZE[size],
          className,
        )}
      >
        {(title || description) && (
          /* Oyna sarlavhasi — hujjat qatori: bosh harfli yorliq va ostida chiziq. */
          <header className="flex items-start justify-between gap-3 border-b border-border bg-surface-2 px-3 py-2">
            <div className="min-w-0">
              {title && (
                <h2 id={titleId} className="intel-micro intel-micro-wrap !text-[11px] !text-fg">
                  {title}
                </h2>
              )}
              {description && (
                <p id={descId} className="mt-0.5 text-[12px] leading-4 text-muted">
                  {description}
                </p>
              )}
            </div>
            <IconButton icon={X} label="Yopish" size="sm" onClick={onClose} className="-mr-1 -mt-0.5" />
          </header>
        )}
        {!title && !description && <IconButton icon={X} label="Yopish" size="sm" onClick={onClose} className="!absolute right-2 top-2 z-10" />}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-1.5 border-t border-border bg-surface-2 px-3 py-2">{footer}</footer>}
        {!footer && <div className="h-2" />}
      </div>
    </div>,
    document.body,
  );
}
