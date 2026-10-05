import { useId } from 'react';
import { cn } from './cn';
import { TONE_TEXT, type Tone } from './tones';

export interface SparklineProps {
  /** Ketma-ket qiymatlar (eskisi birinchi). `null` — o'sha kun ma'lumot yo'q (uzilish). */
  values: ReadonlyArray<number | null>;
  tone?: Tone;
  /** Piksel balandlik; kenglik — konteynerga moslashadi. */
  height?: number;
  /** Y o'qi chegaralari (masalan foiz uchun 0–100). Standart — ma'lumotdan. */
  min?: number;
  max?: number;
  /** Oxirgi nuqtani belgilash. */
  showLast?: boolean;
  ariaLabel?: string;
  className?: string;
}

/** Kichik trend chizig'i (KPI plitkalari ichida): chiziq + yumshoq maydon. */
export function Sparkline({ values, tone = 'primary', height = 32, min, max, showLast = true, ariaLabel, className }: SparklineProps) {
  const gradientId = useId();
  const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (values.length < 2 || nums.length < 2) return null;

  const lo = min ?? Math.min(...nums);
  const hi = max ?? Math.max(...nums);
  const span = hi - lo || 1;
  const W = 100;
  const H = height;
  const pad = 3;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => pad + (1 - (v - lo) / span) * (H - pad * 2);

  // Uzilishlar (null) — alohida bo'laklar.
  const segments: Array<Array<[number, number]>> = [];
  let current: Array<[number, number]> = [];
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push([x(i), y(v)]);
  });
  if (current.length) segments.push(current);

  const line = segments.map((seg) => seg.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(2)} ${py.toFixed(2)}`).join(' ')).join(' ');
  const areas = segments
    .filter((seg) => seg.length > 1)
    .map((seg) => `M${seg[0][0].toFixed(2)} ${H} ${seg.map(([px, py]) => `L${px.toFixed(2)} ${py.toFixed(2)}`).join(' ')} L${seg[seg.length - 1][0].toFixed(2)} ${H} Z`)
    .join(' ');
  let lastIndex = values.length - 1;
  while (lastIndex >= 0 && (values[lastIndex] === null || !Number.isFinite(values[lastIndex] as number))) lastIndex -= 1;
  const last = lastIndex >= 0 ? [x(lastIndex), y(values[lastIndex] as number)] : null;

  return (
    <div className={cn('relative w-full', TONE_TEXT[tone], className)} style={{ height }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full overflow-visible"
        role={ariaLabel ? 'img' : undefined}
        aria-label={ariaLabel}
        aria-hidden={ariaLabel ? undefined : true}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.16" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areas} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="miter" strokeLinecap="butt" vectorEffect="non-scaling-stroke" />
      </svg>
      {showLast && last && (
        <span
          className="absolute h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-[1px] bg-current ring-1 ring-surface"
          style={{ left: `${last[0]}%`, top: last[1] }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
