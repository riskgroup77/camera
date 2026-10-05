import { cn, formatUzDate, TONE_SOLID } from '../../ui';
import type { CalendarDay } from '../../lib/situationApi';
import { statusMeta } from '../../lib/studentAttendance';
import { UZ_WEEKDAYS_SHORT, parseIsoDate } from '../../lib/uzDate';

/** Oxirgi kunlar chizig'i: har kun — rangli katak (holat), ostida hafta kuni.
 *  Drawer va kartalarda qisqa "so'nggi 14 kun" ko'rinishi uchun. */
export function DayStrip({ days, onPick, className }: { days: readonly CalendarDay[]; onPick?: (date: string) => void; className?: string }) {
  return (
    <ol className={cn('grid gap-1', className)} style={{ gridTemplateColumns: `repeat(${Math.max(days.length, 1)}, minmax(0, 1fr))` }}>
      {days.map((day) => {
        const meta = statusMeta(day.status);
        const weekday = UZ_WEEKDAYS_SHORT[(parseIsoDate(day.date).getUTCDay() + 6) % 7];
        const label = `${formatUzDate(day.date, { weekday: true, year: false })}: ${meta.label}${day.checkIn ? `, ${day.checkIn}` : ''}`;
        const muted = meta.tone === 'neutral';
        const cell = (
          <>
            <span
              className={cn(
                'block h-6 w-full rounded-[5px]',
                muted ? 'border border-dashed border-border-strong bg-transparent' : TONE_SOLID[meta.tone],
                day.status === 'kutilmoqda' && 'border-solid bg-surface-3',
              )}
            />
            <span className="mt-1 block text-center text-[10px] leading-none text-subtle">{weekday}</span>
          </>
        );
        return (
          <li key={day.date} title={label}>
            {onPick ? (
              <button type="button" onClick={() => onPick(day.date)} aria-label={label} className="block w-full rounded-[5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                {cell}
              </button>
            ) : (
              <span aria-label={label} role="img" className="block">
                {cell}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
