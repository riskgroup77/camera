import { useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatPercent, formatUzDate, useChartTheme } from '../../ui';
import { minutesToClock } from './time';
import { UZ_WEEKDAYS_SHORT, parseIsoDate } from '../../lib/uzDate';

export interface TrendChartPoint {
  /** YYYY-MM-DD */
  date: string;
  /** 0–100 yoki null (ma'lumot yo'q) */
  rate: number | null;
  /** Kun boshidan daqiqa (o'rtacha kelish) — ixtiyoriy ikkinchi seriya. */
  arrivalMinutes?: number | null;
}

export interface TrendChartProps {
  points: readonly TrendChartPoint[];
  height?: number;
  /** Maqsad chizig'i (standart 85%). `null` — chizilmaydi. */
  target?: number | null;
  /** Eng past kunni belgilash. */
  markLowest?: boolean;
  rateLabel?: string;
  ariaLabel?: string;
}

function dayTick(iso: string): string {
  const d = parseIsoDate(iso);
  return `${d.getUTCDate()} ${UZ_WEEKDAYS_SHORT[(d.getUTCDay() + 6) % 7]}`;
}

/** Kunlik davomat foizi (maydon, chap o'q) + o'rtacha kelish vaqti (chiziq,
 *  o'ng o'q) + maqsad chizig'i va eng past kun belgisi. */
export function TrendChart({ points, height = 260, target = 85, markLowest = true, rateLabel = 'Davomat', ariaLabel = 'Kunlik davomat va kelish vaqti' }: TrendChartProps) {
  const theme = useChartTheme();
  const data = useMemo(() => points.map((p) => ({ ...p, label: dayTick(p.date) })), [points]);
  const hasArrival = points.some((p) => p.arrivalMinutes !== null && p.arrivalMinutes !== undefined);
  // Barqaror havola: har renderda yangi obyekt recharts'ni qayta chizardi.
  const margin = useMemo(() => ({ top: 16, right: hasArrival ? 0 : 8, bottom: 0, left: 0 }), [hasArrival]);
  const arrivals = points.map((p) => p.arrivalMinutes).filter((m): m is number => m !== null && m !== undefined);
  const aMin = arrivals.length ? Math.floor((Math.min(...arrivals) - 10) / 15) * 15 : 420;
  const aMax = arrivals.length ? Math.ceil((Math.max(...arrivals) + 10) / 15) * 15 : 600;
  const rates = points.map((p) => p.rate).filter((r): r is number => r !== null);
  const rMin = rates.length ? Math.max(0, Math.floor((Math.min(...rates, target ?? 100) - 5) / 10) * 10) : 0;
  const lowest = markLowest && rates.length > 2 ? data.reduce<(typeof data)[number] | null>((lo, p) => (p.rate !== null && (lo === null || p.rate < (lo.rate ?? 101)) ? p : lo), null) : null;

  return (
    <div style={{ height }} className="-ml-2 w-[calc(100%+0.5rem)]" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={margin}>
          <defs>
            <linearGradient id="trendchart-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={theme.primary} stopOpacity={0.2} />
              <stop offset="100%" stopColor={theme.primary} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={theme.grid} />
          <XAxis dataKey="label" tick={theme.axisTick} tickLine={false} axisLine={{ stroke: theme.grid }} interval="preserveStartEnd" minTickGap={10} />
          <YAxis yAxisId="rate" domain={[rMin, 100]} tickFormatter={(v) => `${v}%`} tick={theme.axisTick} tickLine={false} axisLine={false} width={42} />
          {hasArrival && (
            <YAxis yAxisId="arr" orientation="right" domain={[aMin, aMax]} tickFormatter={minutesToClock} tick={theme.axisTick} tickLine={false} axisLine={false} width={44} />
          )}
          {target !== null && (
            <ReferenceLine
              yAxisId="rate"
              y={target}
              stroke={theme.success}
              strokeDasharray="4 4"
              strokeOpacity={0.7}
              label={{ value: `Maqsad ${target}%`, position: 'insideTopLeft', fill: theme.success, fontSize: 10 }}
            />
          )}
          <Tooltip
            {...theme.tooltip}
            cursor={{ stroke: theme.axis, strokeDasharray: '3 3' }}
            labelFormatter={(_, payload) => {
              const date = payload?.[0]?.payload?.date as string | undefined;
              return date ? formatUzDate(date, { weekday: true, year: false }) : '';
            }}
            formatter={(value, name) =>
              name === 'arrivalMinutes'
                ? [minutesToClock(value as number | null), "O'rtacha kelish"]
                : [value === null || value === undefined ? "Ma'lumot yo'q" : formatPercent(Number(value), 1), rateLabel]
            }
          />
          <Area
            yAxisId="rate"
            type="monotone"
            dataKey="rate"
            stroke={theme.primary}
            strokeWidth={2}
            fill="url(#trendchart-fill)"
            connectNulls
            dot={{ r: 2.5, fill: theme.primary, stroke: theme.surface, strokeWidth: 1.5 }}
            activeDot={{ r: 5, fill: theme.primary, stroke: theme.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
          {hasArrival && (
            <Line
              yAxisId="arr"
              type="monotone"
              dataKey="arrivalMinutes"
              stroke={theme.warning}
              strokeWidth={1.75}
              strokeDasharray="5 3"
              dot={false}
              activeDot={{ r: 4, fill: theme.warning }}
              connectNulls
              isAnimationActive={false}
            />
          )}
          {lowest && lowest.rate !== null && (
            <ReferenceDot
              yAxisId="rate"
              x={lowest.label}
              y={lowest.rate}
              r={5}
              fill={theme.danger}
              stroke={theme.surface}
              strokeWidth={2}
              label={{ value: `${Math.round(lowest.rate)}%`, position: 'bottom', fill: theme.danger, fontSize: 10, fontWeight: 600 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Grafik ostidagi rang izohi. */
export function TrendLegend({ arrival = true }: { arrival?: boolean }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <li className="inline-flex items-center gap-1.5">
        <span className="h-0.5 w-4 rounded bg-primary" aria-hidden="true" />
        Davomat, %
      </li>
      {arrival && (
        <li className="inline-flex items-center gap-1.5">
          <span className="h-0 w-4 border-t-2 border-dashed border-warning" aria-hidden="true" />
          O'rtacha kelish vaqti
        </li>
      )}
      <li className="inline-flex items-center gap-1.5">
        <span className="h-0 w-4 border-t border-dashed border-success" aria-hidden="true" />
        Maqsad
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-danger" aria-hidden="true" />
        Eng past kun
      </li>
    </ul>
  );
}
