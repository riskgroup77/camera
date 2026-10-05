import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { cn } from './cn';

export type MenuEntry =
  | {
      label: string;
      icon?: LucideIcon;
      onSelect?: () => void;
      /** Ichki havola (navigate). */
      to?: string;
      danger?: boolean;
      disabled?: boolean;
      /** O'ngda kichik izoh (masalan klaviatura yorlig'i). */
      hint?: string;
    }
  | 'separator';

export interface MenuTriggerProps {
  ref: (el: HTMLButtonElement | null) => void;
  onClick: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  'aria-haspopup': 'menu';
  'aria-expanded': boolean;
  'aria-controls': string;
}

export interface MenuProps {
  /** Tugmani chizuvchi funksiya: berilgan props'ni o'z tugmangizga yoying. */
  trigger: (props: MenuTriggerProps) => ReactNode;
  items: MenuEntry[];
  /** Ro'yxat tepasida (masalan foydalanuvchi ismi). */
  header?: ReactNode;
  align?: 'start' | 'end';
  /** Ochilish yo'nalishi. */
  side?: 'bottom' | 'top';
  className?: string;
  width?: string;
}

/** Ochiladigan menyu: ↑ ↓ Home End, Esc, tashqarini bosganda yopiladi. */
export function Menu({ trigger, items, header, align = 'end', side = 'bottom', className, width = 'w-60' }: MenuProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const navigate = useNavigate();

  const actionable = items
    .map((item, index) => (item !== 'separator' && !item.disabled ? index : -1))
    .filter((index) => index >= 0);

  function focusItem(position: number) {
    const index = actionable[(position + actionable.length) % actionable.length];
    itemRefs.current[index]?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  function close(returnFocus = true) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = itemRefs.current.findIndex((el) => el === document.activeElement);
    const position = actionable.indexOf(current);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusItem(position + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusItem(position <= 0 ? actionable.length - 1 : position - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusItem(actionable.length - 1);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === 'Tab') {
      close(false);
    }
  }

  const triggerProps: MenuTriggerProps = {
    ref: (el) => {
      triggerRef.current = el;
    },
    onClick: () => {
      setOpen((value) => !value);
    },
    onKeyDown: (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setOpen(true);
        window.setTimeout(() => focusItem(event.key === 'ArrowUp' ? actionable.length - 1 : 0), 0);
      }
    },
    'aria-haspopup': 'menu',
    'aria-expanded': open,
    'aria-controls': menuId,
  };

  return (
    <div ref={rootRef} className={cn('relative inline-flex', className)}>
      {trigger(triggerProps)}
      {open && (
        <div
          id={menuId}
          role="menu"
          onKeyDown={onMenuKeyDown}
          className={cn(
            'absolute z-50 animate-pop-in overflow-hidden rounded-card border border-border-strong bg-surface text-fg shadow-pop',
            width,
            align === 'end' ? 'right-0' : 'left-0',
            side === 'bottom' ? 'top-full mt-2' : 'bottom-full mb-2',
          )}
        >
          {header && <div className="border-b border-border bg-surface-2 px-2.5 py-2">{header}</div>}
          <div className="p-1">
            {items.map((item, index) => {
              if (item === 'separator') return <div key={`sep-${index}`} role="separator" className="my-1 h-px bg-border" />;
              const Icon = item.icon;
              return (
                <button
                  key={item.label}
                  ref={(el) => {
                    itemRefs.current[index] = el;
                  }}
                  type="button"
                  role="menuitem"
                  tabIndex={-1}
                  disabled={item.disabled}
                  onClick={() => {
                    close();
                    if (item.to) navigate(item.to);
                    item.onSelect?.();
                  }}
                  className={cn(
                    'flex h-7 w-full items-center gap-2 rounded-[2px] px-2 text-left text-[13px] outline-none transition-colors disabled:opacity-40',
                    item.danger ? 'text-danger hover:bg-danger-soft focus:bg-danger-soft' : 'text-fg hover:bg-surface-2 focus:bg-surface-2',
                  )}
                >
                  {Icon && <Icon size={14} aria-hidden="true" className={item.danger ? undefined : 'text-muted'} />}
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.hint && <span className="intel-code text-[11px] text-subtle">{item.hint}</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
