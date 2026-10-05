import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { TONE_SOFT, cn, type Tone } from '../../ui';

export interface DeltaBadgeProps {
  /** O'zgarish (joriy − oldingi). `null` — taqqoslash yo'q. */
  value: number | null | undefined;
  /** Qaysi yo'nalish yaxshi: 'up' (davomat), 'down' (kechikish), 'none'. */
  better?: 'up' | 'down' | 'none';
  /** Qiymatdan keyingi birlik: "pp" (foiz punkti), "daq", "" ... */
  unit?: string;
  digits?: number;
  /** `null` bo'lganda ko'rsatiladigan matn (standart: yashiriladi). */
  emptyLabel?: string;
  title?: string;
  size?: 'sm' | 'md';
  className?: string;
}

/** Oldingi davrga nisbatan o'zgarish: ↑ +3,2 pp (yashil/qizil/neytral). */
export function DeltaBadge({ value, better = 'up', unit = '', digits = 1, emptyLabel, title, size = 'sm', className }: DeltaBadgeProps) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return emptyLabel ? <span className={cn('text-xs text-subtle', className)}>{emptyLabel}</span> : null;
  }
  const rounded = Number(value.toFixed(digits));
  const Icon = rounded === 0 ? Minus : rounded > 0 ? ArrowUpRight : ArrowDownRight;
  let tone: Tone = 'neutral';
  if (rounded !== 0 && better !== 'none') tone = (better === 'up' ? rounded > 0 : rounded < 0) ? 'success' : 'danger';
  const text = `${rounded > 0 ? '+' : ''}${rounded.toLocaleString('ru-RU', { maximumFractionDigits: digits })}${unit ? ` ${unit}` : ''}`;
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-0.5 rounded-full font-semibold tabular-nums',
        size === 'sm' ? 'h-5 px-1.5 text-[11px]' : 'h-6 px-2 text-xs',
        TONE_SOFT[tone],
        className,
      )}
    >
      <Icon size={size === 'sm' ? 12 : 14} aria-hidden="true" />
      {text}
    </span>
  );
}
