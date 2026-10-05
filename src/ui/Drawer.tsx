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

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  subtitle?: ReactNode;
  /** Sarlavha yonida (yopish tugmasidan oldin) — masalan "To'liq sahifa" havolasi. */
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: keyof typeof SIZE;
  /** Panel elementi — ustida boshqa dialog ochilganini bilish uchun
   *  (topDialogPanel bilan solishtiriladi). */
  panelRef?: RefObject<HTMLElement | null>;
}

/** O'ngdan chiqadigan panel — ro'yxatdan chiqmasdan tafsilotni ko'rish
 *  (hodisa, shaxs, kamera). Telefonda to'liq kenglikda. */
export function Drawer({ open, onClose, title, subtitle, actions, children, footer, size = 'md', panelRef: externalRef }: DrawerProps) {
  const ownRef = useRef<HTMLElement>(null);
  const panelRef = externalRef ?? ownRef;
  const titleId = useId();
  useDialog(open, onClose, panelRef);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
        className={cn('relative flex h-full w-full animate-slide-in-right flex-col border-l border-border-strong bg-surface text-fg shadow-pop outline-none', SIZE[size])}
      >
        <header className="flex items-start justify-between gap-3 border-b-2 border-border-strong bg-surface-2 px-3 py-2">
          <div className="min-w-0">
            {title && (
              <h2 id={titleId} className="intel-micro truncate !text-[11px] !text-fg">
                {title}
              </h2>
            )}
            {subtitle && <p className="intel-code mt-0.5 text-[12px] leading-4 text-muted">{subtitle}</p>}
          </div>
          <div className="-mr-1 flex shrink-0 items-center gap-1">
            {actions}
            <IconButton icon={X} label="Yopish" size="sm" onClick={onClose} />
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-1.5 border-t border-border bg-surface-2 px-3 py-2">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  );
}
