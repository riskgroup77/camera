import { useRef, type KeyboardEvent } from 'react';
import { cn, focusRing } from './cn';
import type { TabItem } from './urlTab';

export interface TabsProps<T extends string> {
  tabs: readonly TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** 'underline' — sahifa bo'limlari (Page ostida); 'segmented' — kichik almashtirgich (davr, ko'rinish). */
  variant?: 'underline' | 'segmented';
  size?: 'sm' | 'md';
  ariaLabel?: string;
  className?: string;
  /** Har bir tab paneli id'si uchun prefiks (aria-controls). */
  idPrefix?: string;
}

/** Tablar: klaviatura bilan (← → Home End), aria roli bilan. */
export function Tabs<T extends string>({ tabs, value, onChange, variant = 'underline', size = 'md', ariaLabel = "Bo'limlar", className, idPrefix }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const enabled = tabs.map((tab, i) => (tab.disabled ? -1 : i)).filter((i) => i >= 0);
    const position = enabled.indexOf(index);
    let target: number | undefined;
    if (event.key === 'ArrowRight') target = enabled[(position + 1) % enabled.length];
    else if (event.key === 'ArrowLeft') target = enabled[(position - 1 + enabled.length) % enabled.length];
    else if (event.key === 'Home') target = enabled[0];
    else if (event.key === 'End') target = enabled[enabled.length - 1];
    if (target === undefined) return;
    event.preventDefault();
    refs.current[target]?.focus();
    onChange(tabs[target].id);
  }

  const underline = variant === 'underline';

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        underline
          ? 'no-scrollbar -mb-px flex gap-0.5 overflow-x-auto border-b border-border-strong sm:gap-3'
          : 'no-scrollbar inline-flex max-w-full overflow-x-auto rounded-control border border-border bg-surface-2',
        className,
      )}
    >
      {tabs.map((tab, index) => {
        const active = tab.id === value;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-tab-${tab.id}` : undefined}
            aria-controls={idPrefix ? `${idPrefix}-panel-${tab.id}` : undefined}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={tab.disabled}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              // Yorliqlar bosh harfli mikro-yorliq: bu bo'lim nomlari.
              // Yo'naltiruvchi yorliq — mikro-yorliqdan bir oz kattaroq (11px),
              // chunki bu o'qiladigan navigatsiya, ustun sarlavhasi emas.
              'intel-micro relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap !text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
              focusRing,
              underline
                ? cn(
                    'border-b-2 px-2',
                    size === 'sm' ? 'h-8' : 'h-9',
                    active ? 'border-primary !text-fg' : 'border-transparent hover:border-border-strong hover:!text-fg',
                  )
                : cn(
                    'border-r border-border px-2.5 last:border-r-0',
                    size === 'sm' ? 'h-7' : 'h-8',
                    active ? 'bg-primary !text-primary-fg' : 'hover:bg-surface-3 hover:!text-fg',
                  ),
            )}
          >
            {Icon && <Icon size={13} aria-hidden="true" className="shrink-0" />}
            {tab.label}
            {tab.count !== undefined && tab.count !== null && (
              <span
                className={cn(
                  'intel-code rounded-[2px] border px-1 text-[10px] font-bold leading-[14px] tracking-normal',
                  active && !underline
                    ? 'border-transparent bg-primary-fg/20 text-primary-fg'
                    : active
                      ? 'border-primary/30 bg-primary-soft text-primary'
                      : 'border-border bg-surface-2 text-muted',
                )}
              >
                {tab.count.toLocaleString('ru-RU')}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
