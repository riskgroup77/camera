import { forwardRef, useId } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn, controlBase, controlSizes, type ControlSize } from './cn';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  /** Bo'sh qiymatli birinchi variant ("Barcha fakultetlar"). Berilmasa — yo'q. */
  placeholder?: string;
  /** Maydon ichida chapda ko'rinadigan qisqa yorliq ("Fakultet:"). */
  label?: string;
  ariaLabel?: string;
  size?: ControlSize;
  disabled?: boolean;
  invalid?: boolean;
  /** Filtr sifatida: qiymat tanlanganda ajralib turadi. */
  highlightActive?: boolean;
  className?: string;
  id?: string;
  'aria-describedby'?: string;
}

/** Tanlash maydoni (native <select>): telefonda tizim ro'yxati ochiladi,
 *  klaviatura va ekran o'quvchi bilan to'liq ishlaydi. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { value, onChange, options, placeholder, label, ariaLabel, size = 'md', disabled, invalid, highlightActive = false, className, id, ...rest },
  ref,
) {
  const autoId = useId();
  const selectId = id ?? autoId;
  const active = highlightActive && value !== '';
  return (
    <div className={cn('relative inline-flex w-full min-w-0 sm:w-auto', className)}>
      {label && (
        <label htmlFor={selectId} className="intel-micro pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2">
          {label}
        </label>
      )}
      <select
        ref={ref}
        id={selectId}
        value={value}
        disabled={disabled}
        aria-label={label ? undefined : ariaLabel ?? placeholder}
        aria-invalid={invalid || undefined}
        aria-describedby={rest['aria-describedby']}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          'intel-code',
          controlBase,
          controlSizes[size],
          'cursor-pointer appearance-none truncate pr-7 font-medium',
          active && 'border-primary bg-primary-soft text-primary',
          invalid && 'border-danger',
        )}
        // Bosh harfli mikro-yorliq kengligiga joy (10px mono + 0.11em
        // harf oralig'i ≈ 0.42rem/belgi).
        style={label ? { paddingLeft: `calc(${label.length * 0.42}rem + 0.9rem)` } : undefined}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown size={13} aria-hidden="true" className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-subtle" />
    </div>
  );
});
