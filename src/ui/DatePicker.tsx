import { useId, useRef } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { addDays, todayInTashkent } from '../lib/uzDate';
import { cn, focusRing, type ControlSize } from './cn';
import { clampIsoDate, formatUzDate, isIsoDate, relativeDayLabel } from './dates';

export interface DatePickerProps {
  /** "YYYY-MM-DD". */
  value: string;
  onChange: (value: string) => void;
  min?: string;
  /** Standart: bugun (kelajakdagi davomat yo'q). `null` — cheklovsiz. */
  max?: string | null;
  /** "Bugun" / "Kecha" tugmalari. */
  quick?: boolean;
  /** ‹ › — bir kun oldin/keyin. */
  stepper?: boolean;
  size?: Exclude<ControlSize, 'lg'>;
  ariaLabel?: string;
  /** Tor joy (telefon, yuqori panel): qisqa yozuv. */
  compact?: boolean;
  className?: string;
}

/** Bitta sana: chiroyli yozuvli tugma (bosilganda tizim kalendari ochiladi),
 *  ‹ › qadamlar va "Bugun/Kecha" tezkor tugmalari. */
export function DatePicker({
  value,
  onChange,
  min,
  max,
  quick = true,
  stepper = true,
  size = 'md',
  ariaLabel = 'Sana',
  compact = false,
  className,
}: DatePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const today = todayInTashkent();
  const upper = max === null ? undefined : (max ?? today);
  const relative = relativeDayLabel(value, today);
  const label = isIsoDate(value)
    ? compact
      ? (relative ?? formatUzDate(value, { year: false }))
      : `${relative ? `${relative}, ` : ''}${formatUzDate(value, { year: !relative })}`
    : 'Sanani tanlang';

  function commit(next: string) {
    if (!isIsoDate(next)) return;
    onChange(clampIsoDate(next, min, upper));
  }

  function openPicker() {
    const input = inputRef.current;
    if (!input) return;
    try {
      if (typeof input.showPicker === 'function') {
        input.showPicker();
        return;
      }
    } catch {
      /* showPicker faqat foydalanuvchi harakatida — pastdagi zaxira */
    }
    input.focus();
    input.click();
  }

  // Boshqaruv balandliklari cn.ts'dagi controlSizes bilan bir xil.
  const h = size === 'sm' ? 'h-7' : 'h-8';
  const canPrev = !min || value > min;
  const canNext = !upper || value < upper;
  const stepClass = cn(
    'inline-flex shrink-0 items-center justify-center text-muted transition-colors hover:bg-surface-2 hover:text-fg disabled:pointer-events-none disabled:opacity-40',
    focusRing,
    h,
    size === 'sm' ? 'w-6' : 'w-7',
  );

  return (
    <div className={cn('inline-flex max-w-full items-center gap-1.5', className)}>
      <div className={cn('relative inline-flex min-w-0 items-stretch rounded-control border border-border bg-surface', h)}>
        {stepper && (
          <button type="button" className={cn(stepClass, 'rounded-l-control border-r border-border')} onClick={() => commit(addDays(value, -1))} disabled={!canPrev} aria-label="Oldingi kun">
            <ChevronLeft size={14} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          onClick={openPicker}
          aria-label={`${ariaLabel}: ${isIsoDate(value) ? formatUzDate(value, { weekday: true }) : 'tanlanmagan'}. O'zgartirish`}
          className={cn(
            // Sana — o'lchov: monoshrift, teng kenglikdagi raqamlar.
            'intel-code inline-flex min-w-0 items-center gap-1.5 px-2 font-medium text-fg transition-colors hover:bg-surface-2',
            size === 'sm' ? 'text-[12px]' : 'text-[13px]',
            !stepper && 'rounded-control',
            focusRing,
          )}
        >
          <CalendarDays size={13} className="shrink-0 text-muted" aria-hidden="true" />
          <span className="truncate">{label}</span>
        </button>
        {stepper && (
          <button type="button" className={cn(stepClass, 'rounded-r-control border-l border-border')} onClick={() => commit(addDays(value, 1))} disabled={!canNext} aria-label="Keyingi kun">
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        )}
        {/* Tizim kalendari shu ko'rinmas maydon orqali ochiladi (showPicker). */}
        <input
          ref={inputRef}
          id={inputId}
          type="date"
          tabIndex={-1}
          aria-hidden="true"
          value={isIsoDate(value) ? value : ''}
          min={min}
          max={upper}
          onChange={(event) => commit(event.target.value)}
          className="pointer-events-none absolute bottom-0 left-8 h-px w-px opacity-0"
        />
      </div>
      {quick && (
        <div className="hidden items-center gap-1 sm:inline-flex">
          {[
            { label: 'Bugun', date: today },
            { label: 'Kecha', date: addDays(today, -1) },
          ].map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => commit(item.date)}
              aria-pressed={value === item.date}
              className={cn(
                'intel-micro rounded-control border px-2 transition-colors',
                h,
                value === item.date
                  ? 'border-primary bg-primary-soft !text-primary'
                  : 'border-border hover:bg-surface-2 hover:!text-fg',
                focusRing,
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
