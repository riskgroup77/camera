import { useEffect, useRef, useState, type ReactNode } from 'react';
import { buttonClasses, cn } from '../../ui';

/** Videodevor asboblaridagi ochiladigan panel (ko'rinishlar, tur, yordam).
 * Tashqarida bosilganda yoki Escape bilan yopiladi. Ichida forma bo'lgani
 * uchun (nom kiritish, slayder) oddiy `Menu` emas — erkin tarkibli panel. */
export default function WallPopover({
  label,
  icon,
  children,
  active = false,
  align = 'left',
  title,
  ariaLabel,
  widthClass = 'w-80',
}: {
  label?: ReactNode;
  icon?: ReactNode;
  children: (close: () => void) => ReactNode;
  active?: boolean;
  align?: 'left' | 'right';
  title?: string;
  /** Faqat ikonkali tugma uchun majburiy. */
  ariaLabel?: string;
  widthClass?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onPointer);
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const iconOnly = !label;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={ariaLabel}
        title={title}
        className={buttonClasses({
          variant: active ? 'soft' : 'secondary',
          size: 'md',
          className: cn(iconOnly && 'w-9 px-0', open && !active && 'border-border-strong bg-surface-2'),
        })}
      >
        {icon}
        {label}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={ariaLabel ?? title}
          className={cn(
            'absolute top-full z-50 mt-1 max-w-[calc(100vw-2rem)] animate-pop-in rounded-[2px] border border-border-strong bg-surface p-3 text-fg shadow-pop',
            // Telefonda tugma o'ngda bo'lsa panel ekrandan chiqib ketardi.
            'max-sm:fixed max-sm:inset-x-4 max-sm:top-auto max-sm:w-auto',
            widthClass,
            align === 'right' ? 'right-0' : 'left-0',
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
