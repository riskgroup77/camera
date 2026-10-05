import { useRef, type KeyboardEvent } from 'react';
import { MicroLabel, Skeleton, cn } from '../../ui';
import { CELL_STATUS_LABEL, dayLabel, keyboardTarget, leadingBlanks, monthLabel, monthOf, type CalendarCell, type CellStatus } from '../../lib/attendanceCalendar';
import { UZ_WEEKDAYS_SHORT } from '../../lib/uzDate';
import { STATUS_MARK } from './readout';

/** Katakdagi "binoda bo'lish" chizig'i shu davomiylikda to'la bo'ladi. */
const FULL_DAY_MINUTES = 9 * 60;

/**
 * Kalendar — o'lchov to'ri, bezak emas: kataklar to'rtburchak, oralarida
 * soch tolasidek chiziq, raqamlar monoshriftda.
 *
 * Holatlar bir-biridan RANG BILAN EMAS, belgi bilan ham ajraladi:
 * "dam olish" va "ma'lumot yo'q" bir xil kulrang bo'lsa ham, birinchisi
 * DO, ikkinchisi — uzilgan chegara bilan chiziladi. Bu farq muhim:
 * dam olish kuni odam "kelmagan" emas.
 */
const CELL_STYLE: Record<CellStatus, string> = {
  keldi: 'border-transparent bg-success-soft text-success',
  kech_keldi: 'border-transparent bg-warning-soft text-warning',
  kelmadi: 'border-transparent bg-danger-soft text-danger',
  dam_olish: 'border-transparent bg-surface-2 text-subtle',
  malumot_yoq: 'border-dashed border-border-strong bg-surface text-muted',
  kelajak: 'border-transparent bg-transparent text-subtle/60',
};

const CALENDAR_LEGEND: CellStatus[] = ['keldi', 'kech_keldi', 'kelmadi', 'malumot_yoq', 'dam_olish'];

function DayCell({ cell, selected, dimmed, onOpen }: { cell: CalendarCell; selected: boolean; dimmed: boolean; onOpen: (date: string) => void }) {
  const future = cell.status === 'kelajak';
  const details = [CELL_STATUS_LABEL[cell.status], cell.checkIn ? `keldi ${cell.checkIn}` : null, cell.checkOut ? `ketdi ${cell.checkOut}` : null, cell.earlyLeave ? 'erta ketdi' : null]
    .filter(Boolean)
    .join(', ');
  const fill = cell.presenceMinutes ? Math.min(cell.presenceMinutes / FULL_DAY_MINUTES, 1) : 0;
  return (
    <button
      type="button"
      data-date={cell.date}
      disabled={future}
      onClick={() => onOpen(cell.date)}
      aria-label={`${dayLabel(cell.date)} — ${details}`}
      title={details}
      className={cn(
        'relative flex min-h-[2.75rem] flex-col justify-between border p-1 text-left sm:min-h-[3.5rem] sm:p-1.5',
        CELL_STYLE[cell.status],
        future ? 'cursor-default' : 'hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
        cell.isToday && 'shadow-[inset_0_0_0_2px_rgb(var(--c-primary))]',
        selected && 'shadow-[inset_0_0_0_3px_rgb(var(--c-primary)/0.55)]',
        dimmed && 'opacity-40',
      )}
    >
      <span className="flex items-center justify-between gap-1">
        <span className={cn('intel-code text-[12px]', cell.isToday ? 'font-bold' : 'font-semibold')}>{cell.day}</span>
        <span className="flex items-center gap-1">
          {cell.earlyLeave && <span className="h-1.5 w-1.5 shrink-0 rounded-[1px] bg-warning" aria-hidden="true" />}
          {/* Rang yolg'iz qolmasin: kelajakdan boshqa har katakda belgi bor. */}
          {!future && (
            <span aria-hidden="true" className="intel-code text-[9px] font-bold opacity-70">
              {STATUS_MARK[cell.status] ?? '—'}
            </span>
          )}
        </span>
      </span>
      {cell.checkIn && (
        <span className="intel-code hidden truncate text-[10px] font-medium opacity-90 sm:block">
          {cell.checkIn}
          {cell.checkOut ? `–${cell.checkOut}` : ''}
        </span>
      )}
      {fill > 0 && (
        <span className="absolute inset-x-1 bottom-0.5 h-[3px] overflow-hidden bg-fg/5" aria-hidden="true">
          <span className="block h-full bg-current opacity-50" style={{ width: `${Math.round(fill * 100)}%` }} />
        </span>
      )}
    </button>
  );
}

/** Oylik davomat kalendari (hafta dushanbadan). Strelkalar bilan kunlar
 *  orasida yuriladi; tanlangan oraliqdan tashqaridagi kunlar xiraroq. */
export function MonthCalendar({
  month,
  cells,
  workingWeekdays,
  selectedDate,
  onOpen,
  range,
  loading,
  showTitle = true,
}: {
  month: string;
  cells: CalendarCell[] | null;
  workingWeekdays: number[];
  selectedDate: string | null;
  onOpen: (date: string) => void;
  range?: { from: string; to: string };
  loading?: boolean;
  showTitle?: boolean;
}) {
  const gridRef = useRef<HTMLDivElement>(null);

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    const date = (event.target as HTMLElement).dataset.date;
    const target = date ? keyboardTarget(date, event.key) : null;
    if (!target || monthOf(target) !== month) return;
    const button = gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${target}"]`);
    if (button && !button.disabled) {
      event.preventDefault();
      button.focus();
    }
  }

  return (
    <div className="min-w-0">
      {showTitle && (
        <h3 className="intel-micro !text-fg border-b border-border bg-surface-2 px-2 py-1">{monthLabel(month)}</h3>
      )}
      <div className="grid grid-cols-7 gap-px border-b border-border bg-border">
        {UZ_WEEKDAYS_SHORT.map((label, index) => (
          <span
            key={label}
            className={cn('bg-surface py-1 text-center', workingWeekdays.includes(index + 1) ? '' : 'bg-surface-2')}
          >
            <MicroLabel>{label}</MicroLabel>
          </span>
        ))}
      </div>
      {loading || !cells ? (
        <div className="grid grid-cols-7 gap-px bg-border">
          {Array.from({ length: 35 }, (_, i) => (
            <Skeleton key={i} className="min-h-[2.75rem] rounded-none sm:min-h-[3.5rem]" />
          ))}
        </div>
      ) : (
        <div ref={gridRef} role="group" aria-label={`${monthLabel(month)} — davomat kalendari`} onKeyDown={handleKey} className="grid grid-cols-7 gap-px bg-border">
          {Array.from({ length: leadingBlanks(month) }, (_, i) => (
            <span key={`blank-${i}`} aria-hidden="true" className="bg-surface" />
          ))}
          {cells.map((cell) => (
            <DayCell
              key={cell.date}
              cell={cell}
              selected={cell.date === selectedDate}
              dimmed={Boolean(range && (cell.date < range.from || cell.date > range.to))}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Kalendar kaliti — qaysi rang va belgi nimani anglatishi. Har ekranda
 *  ochiq turadi: "dam olish" bilan "ma'lumot yo'q" ni chalkashtirmasin. */
export function CalendarLegend({ className }: { className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-2', className)}>
      <MicroLabel>Kalendar kaliti</MicroLabel>
      {CALENDAR_LEGEND.map((status) => (
        <span key={status} className="flex items-center gap-1.5">
          <span className={cn('flex h-4 w-4 items-center justify-center border text-[8px] font-bold', CELL_STYLE[status])} aria-hidden="true">
            {STATUS_MARK[status] ?? '—'}
          </span>
          <span className="text-[11px] text-muted">{CELL_STATUS_LABEL[status]}</span>
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-[1px] bg-warning" aria-hidden="true" />
        <span className="text-[11px] text-muted">Erta ketdi</span>
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-[3px] w-4 bg-subtle" aria-hidden="true" />
        <span className="text-[11px] text-muted">Binoda bo&apos;lish (9 soat — to&apos;liq)</span>
      </span>
    </div>
  );
}
