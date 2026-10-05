import { useId } from 'react';
import { todayInTashkent } from '../lib/uzDate';
import { validateRange, type FixedPreset } from '../lib/reportPeriods';
import { cn, controlBase, controlSizes } from './cn';
import { RANGE_PRESET_LABELS, formatUzRange, rangeForPreset, type DateRangeValue, type RangePreset } from './dates';
import { Tabs } from './Tabs';

export interface DateRangePickerProps {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  /** Tayyor davrlar (standart: Bugun, Hafta, Oy). */
  presets?: readonly FixedPreset[];
  /** "Oraliq" (qo'lda tanlash) varianti. */
  allowCustom?: boolean;
  size?: 'sm' | 'md';
  className?: string;
  /** Tanlangan oraliqni matn bilan ko'rsatish. */
  showSummary?: boolean;
}

const DEFAULT_PRESETS: readonly FixedPreset[] = ['today', 'week', 'month'];

/** Davr: Bugun / Hafta / Oy / Oraliq. Oraliqda ikki sana va tekshiruv
 *  (backend chegarasi — 92 kun). */
export function DateRangePicker({ value, onChange, presets = DEFAULT_PRESETS, allowCustom = true, size = 'md', className, showSummary = true }: DateRangePickerProps) {
  const id = useId();
  const today = todayInTashkent();
  const tabs = [
    ...presets.map((preset) => ({ id: preset as RangePreset, label: RANGE_PRESET_LABELS[preset] })),
    ...(allowCustom ? [{ id: 'custom' as RangePreset, label: 'Oraliq' }] : []),
  ];
  const error = value.preset === 'custom' ? validateRange(value.from, value.to) : null;

  function selectPreset(preset: RangePreset) {
    if (preset === 'custom') onChange({ ...value, preset: 'custom' });
    else onChange(rangeForPreset(preset, today));
  }

  const inputClass = cn('intel-code', controlBase, controlSizes[size], 'w-auto min-w-0');

  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <Tabs tabs={tabs} value={value.preset} onChange={selectPreset} variant="segmented" size={size} ariaLabel="Davr" />
      {value.preset === 'custom' ? (
        <div className="flex flex-wrap items-center gap-1">
          <label htmlFor={`${id}-from`} className="sr-only">
            Boshlanish sanasi
          </label>
          <input
            id={`${id}-from`}
            type="date"
            value={value.from}
            max={value.to || today}
            onChange={(event) => onChange({ ...value, from: event.target.value })}
            className={inputClass}
            aria-invalid={Boolean(error) || undefined}
          />
          <span className="intel-code text-muted" aria-hidden="true">
            –
          </span>
          <label htmlFor={`${id}-to`} className="sr-only">
            Tugash sanasi
          </label>
          <input
            id={`${id}-to`}
            type="date"
            value={value.to}
            min={value.from}
            max={today}
            onChange={(event) => onChange({ ...value, to: event.target.value })}
            className={inputClass}
            aria-invalid={Boolean(error) || undefined}
          />
          {error && (
            <p className="w-full text-[12px] font-medium text-danger" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : (
        showSummary && <span className="intel-code text-[12px] text-muted">{formatUzRange(value.from, value.to)}</span>
      )}
    </div>
  );
}
