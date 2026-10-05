import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { BarChart3 } from 'lucide-react';
import { Card, CardHeader, EmptyState, cn, focusRing, useChartTheme } from '../../ui';
import { monthLabel, shortMonthLabel } from '../../lib/attendanceCalendar';
import type { AttendanceMonth } from '../../types';

// Barqaror havola: har renderda yangi obyekt recharts'ni qayta chizardi.
const CHART_MARGIN = { top: 6, right: 4, bottom: 0, left: 0 };

function rateText(rate: number | null): string {
  return rate === null ? '—' : `${String(rate).replace('.', ',')}%`;
}

/** Oxirgi oylar: yozuvli kunlar (yig'ma ustunlar) va har oyning davomat
 *  foizi. Oy tugmasi kalendarni o'sha oyga o'tkazadi. */
export default function MonthTrend({
  months,
  activeMonth,
  onPick,
  className,
}: {
  months: AttendanceMonth[];
  activeMonth: string | null;
  onPick: (month: string) => void;
  className?: string;
}) {
  const theme = useChartTheme();
  const hasData = months.some((m) => m.recordedDays > 0);
  const data = months.map((m) => ({ month: m.month, keldi: m.present, kech: m.late, kelmadi: m.absent }));

  return (
    <Card className={cn('flex flex-col', className)}>
      <CardHeader title={`Oxirgi ${months.length} oy`} subtitle="Yozuvli kunlar va davomat foizi" icon={BarChart3} />
      <ul className="mb-2 flex flex-wrap gap-3 text-xs text-muted" aria-label="Rang izohi">
        {[
          { c: theme.attendance.keldi, l: 'Keldi' },
          { c: theme.attendance.kechKeldi, l: 'Kech keldi' },
          { c: theme.attendance.kelmadi, l: 'Kelmadi' },
        ].map((i) => (
          <li key={i.l} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm" style={{ background: i.c }} aria-hidden="true" />
            {i.l}
          </li>
        ))}
      </ul>
      {hasData ? (
        <div className="-ml-2 h-44 w-[calc(100%+0.5rem)]" role="img" aria-label="Oylar bo'yicha davomat">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={CHART_MARGIN}>
              <CartesianGrid stroke={theme.grid} vertical={false} />
              <XAxis dataKey="month" tickFormatter={shortMonthLabel} tick={theme.axisTick} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} tick={theme.axisTick} tickLine={false} axisLine={false} width={32} />
              <Tooltip {...theme.tooltip} labelFormatter={(value) => monthLabel(String(value))} />
              <Bar dataKey="keldi" name="Keldi" stackId="k" fill={theme.attendance.keldi} stroke={theme.surface} strokeWidth={2} isAnimationActive={false} />
              <Bar dataKey="kech" name="Kech keldi" stackId="k" fill={theme.attendance.kechKeldi} stroke={theme.surface} strokeWidth={2} isAnimationActive={false} />
              <Bar dataKey="kelmadi" name="Kelmadi" stackId="k" fill={theme.attendance.kelmadi} stroke={theme.surface} strokeWidth={2} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyState compact bordered={false} title="Bu davrda yozuv yo'q" description="Kameralar bu odamni tanimagan yoki davomat qo'lda kiritilmagan." />
      )}
      <div className="mt-3 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {months.map((m) => {
          const active = m.month === activeMonth;
          return (
            <button
              key={m.month}
              type="button"
              onClick={() => onPick(m.month)}
              aria-pressed={active}
              title={`${monthLabel(m.month)}: ${m.recordedDays} ta yozuvli kun`}
              className={cn(
                'rounded-control px-2 py-1.5 text-center transition-colors',
                active ? 'bg-primary text-primary-fg' : 'bg-surface-2 text-muted hover:text-fg',
                focusRing,
              )}
            >
              <span className="block text-[10px] font-medium uppercase tracking-wide opacity-80">{shortMonthLabel(m.month)}</span>
              <span className="block text-sm font-semibold tabular-nums">{rateText(m.rate)}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
