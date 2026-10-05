import { useState } from 'react';
import { cn, formatNumber } from '../../ui';

export interface HeatmapRow {
  label: string;
  values: number[];
  /** Qator oxiridagi izoh (masalan "13% kech"). */
  aside?: string;
}

export interface HeatmapProps {
  rows: HeatmapRow[];
  /** Ustun sarlavhalari (values bilan bir xil uzunlik). */
  columns: string[];
  /** Rang shkalasi maksimumi (standart: eng katta qiymat). */
  max?: number;
  /** Rang: CSS token nomi (primary, success, warning, danger, info). */
  tone?: 'primary' | 'success' | 'warning' | 'danger' | 'info';
  /** Tooltip matni. */
  formatTooltip?: (row: HeatmapRow, columnIndex: number, value: number) => string;
  /** Ajratib ko'rsatiladigan ustunlar (masalan ish boshlanish soati). */
  markColumn?: number;
  ariaLabel?: string;
  className?: string;
}

/** Hafta kuni × soat kabi jadvalli issiqlik xaritasi (recharts'siz, CSS grid).
 *  Rang — tokenning shaffofligi, shuning uchun qorong'i mavzuda ham ishlaydi. */
export function Heatmap({ rows, columns, max, tone = 'primary', formatTooltip, markColumn, ariaLabel, className }: HeatmapProps) {
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);
  const top = max ?? Math.max(0, ...rows.flatMap((r) => r.values));
  const hasAside = rows.some((r) => r.aside);
  const template = `2.75rem repeat(${columns.length}, minmax(1.5rem, 1fr))${hasAside ? ' 3.5rem' : ''}`;
  const hovered = hover ? rows[hover.r] : null;
  const tip =
    hover && hovered
      ? (formatTooltip?.(hovered, hover.c, hovered.values[hover.c] ?? 0) ?? `${hovered.label}, ${columns[hover.c]}: ${formatNumber(hovered.values[hover.c])}`)
      : null;

  return (
    <div className={cn('min-w-0', className)}>
      <div className="overflow-x-auto pb-1">
        <div role="table" aria-label={ariaLabel} className="grid min-w-[30rem] gap-1" style={{ gridTemplateColumns: template }} onMouseLeave={() => setHover(null)}>
          <div role="row" className="contents">
            <span role="columnheader" />
            {columns.map((c, i) => (
              <span key={c} role="columnheader" className={cn('text-center text-[10px] tabular-nums text-muted', i === markColumn && 'font-semibold text-fg')}>
                {c}
              </span>
            ))}
            {hasAside && <span role="columnheader" />}
          </div>
          {rows.map((row, r) => (
            <div role="row" key={row.label} className="contents">
              <span role="rowheader" className="flex items-center text-xs font-medium text-muted">
                {row.label}
              </span>
              {row.values.map((v, c) => {
                const ratio = top > 0 ? v / top : 0;
                const active = hover?.r === r && hover?.c === c;
                return (
                  <span
                    key={c}
                    role="cell"
                    tabIndex={-1}
                    aria-label={`${row.label} ${columns[c]}: ${v}`}
                    onMouseEnter={() => setHover({ r, c })}
                    className={cn(
                      'relative h-7 rounded-[5px] border transition-transform duration-100',
                      v === 0 ? 'border-border/60 bg-surface-2' : 'border-transparent',
                      active && 'z-10 scale-110 ring-2 ring-fg/30',
                      c === markColumn && v === 0 && 'border-dashed',
                    )}
                    style={v > 0 ? { background: `rgb(var(--c-${tone}) / ${(0.12 + ratio * 0.88).toFixed(3)})` } : undefined}
                  >
                    {ratio >= 0.55 && <span className="absolute inset-0 hidden items-center justify-center text-[10px] font-semibold tabular-nums text-white sm:flex">{v}</span>}
                  </span>
                );
              })}
              {hasAside && <span className="flex items-center justify-end text-[11px] tabular-nums text-muted">{row.aside}</span>}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 flex min-h-5 flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span className="font-medium text-fg" aria-live="polite">
          {tip ?? 'Katakka olib boring — batafsil'}
        </span>
        <span className="flex items-center gap-1.5">
          kam
          {[0.12, 0.34, 0.56, 0.78, 1].map((a) => (
            <span key={a} className="h-2.5 w-4 rounded-sm" style={{ background: `rgb(var(--c-${tone}) / ${a})` }} />
          ))}
          ko'p
        </span>
      </div>
    </div>
  );
}
