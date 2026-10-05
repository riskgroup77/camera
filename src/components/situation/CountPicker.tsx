import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import { cn } from '../../ui';

/**
 * Tanlash ro'yxati — har variant yonida bugungi davomat rangli sonlar bilan:
 * yashil — kelganlar, qizil — kelmaganlar (hali kelmaganlar bilan),
 * kulrang — ma'lumoti yo'qlar (yuzi bazada yo'q va h.k.). Oddiy <select>
 * variantlarini bo'yab bo'lmaydi, shuning uchun o'z ro'yxati.
 */

export interface CountOption {
  value: string;
  label: string;
  present: number;
  absent: number;
  noData: number;
  /** Daraxt: ichki bo'linma chekinishi (0 — ildiz). */
  indent?: number;
  /** Bo'lim sarlavhasi — shu variantdan oldin chiqadi, agar oldingisidan farq qilsa. */
  section?: string;
}

function Counts({ option }: { option: Pick<CountOption, 'present' | 'absent' | 'noData'> }) {
  return (
    <span className="flex shrink-0 items-center gap-1.5 text-[12px] font-semibold tabular-nums">
      <span className="min-w-[1.6rem] text-right text-success" title="Kelganlar">{option.present}</span>
      <span className="min-w-[1.6rem] text-right text-danger" title="Kelmaganlar">{option.absent}</span>
      <span className="min-w-[1.6rem] text-right text-subtle" title="Ma’lumoti yo‘q">{option.noData}</span>
    </span>
  );
}

export default function CountPicker({
  label,
  value,
  onChange,
  options,
  allLabel = 'hammasi',
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly CountOption[];
  allLabel?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const root = useRef<HTMLDivElement | null>(null);
  const selected = options.find((o) => o.value === value) ?? null;

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((o) => o.label.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
    setQuery('');
  };

  return (
    <div ref={root} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          'flex h-8 w-full min-w-[12rem] items-center gap-2 rounded-control border bg-surface px-2.5 text-left text-[13px]',
          value ? 'border-primary/60 bg-primary-soft' : 'border-border',
        )}
      >
        <span className="shrink-0 text-muted">{label}:</span>
        <span className="min-w-0 flex-1 truncate font-medium text-fg">{selected?.label ?? allLabel}</span>
        {selected && <Counts option={selected} />}
        <ChevronDown size={14} aria-hidden="true" className="shrink-0 text-subtle" />
      </button>
      {open && (
        <div className="absolute start-0 top-9 z-50 flex max-h-[60vh] w-[max(100%,22rem)] flex-col overflow-hidden rounded-control border border-border bg-surface shadow-card">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-2.5 py-1.5">
            <Search size={14} aria-hidden="true" className="text-subtle" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Qidirish"
              aria-label={`${label} — qidirish`}
              className="h-7 min-w-0 flex-1 bg-transparent text-[13px] outline-none"
            />
            {query && (
              <button type="button" onClick={() => setQuery('')} aria-label="Tozalash" className="text-subtle hover:text-fg">
                <X size={14} />
              </button>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-subtle">
            <span className="flex-1">{label}</span>
            <span className="flex gap-1.5">
              <span className="min-w-[1.6rem] text-right text-success">Keldi</span>
              <span className="min-w-[1.6rem] text-right text-danger">Yo‘q</span>
              <span className="min-w-[1.6rem] text-right">?</span>
            </span>
          </div>
          <ul role="listbox" className="min-h-0 flex-1 overflow-y-auto py-1">
            <li>
              <button
                type="button"
                role="option"
                aria-selected={!value}
                onClick={() => choose('')}
                className={cn('flex w-full items-center px-2.5 py-1.5 text-left text-[13px] hover:bg-surface-2', !value && 'bg-primary-soft')}
              >
                {allLabel}
              </button>
            </li>
            {shown.map((option, index) => (
              <li key={option.value}>
                {option.section && option.section !== shown[index - 1]?.section && (
                  <div className="mt-1 px-2.5 pb-0.5 pt-1.5 text-[10px] font-semibold uppercase tracking-wide text-subtle">
                    {option.section}
                  </div>
                )}
                <button
                  type="button"
                  role="option"
                  aria-selected={option.value === value}
                  onClick={() => choose(option.value)}
                  className={cn(
                    'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] hover:bg-surface-2',
                    option.value === value && 'bg-primary-soft',
                  )}
                >
                  <span
                    className={cn('min-w-0 flex-1 truncate', !option.indent && option.section && 'font-medium')}
                    style={option.indent ? { paddingInlineStart: `${option.indent * 14}px` } : undefined}
                  >
                    {option.indent ? '└ ' : ''}
                    {option.label}
                  </span>
                  <Counts option={option} />
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="px-2.5 py-2 text-[12px] text-muted">Topilmadi</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
