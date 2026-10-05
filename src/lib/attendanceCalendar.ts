import type { AttendanceDay, AttendanceDayStatus } from '../types';
import { UZ_MONTHS, UZ_WEEKDAYS, addDays, parseIsoDate } from './uzDate';

/** Kalendar katagi: yozuv holatlari + yozuvsiz kunlar. Yozuvsiz o'tgan ish
 *  kuni "ma'lumot yo'q" — u hech qachon "kelmadi" deb ko'rsatilmaydi. */
export type CellStatus = AttendanceDayStatus | 'malumot_yoq' | 'kelajak';

export interface CalendarCell {
  date: string;
  day: number;
  status: CellStatus;
  checkIn: string | null;
  checkOut: string | null;
  earlyLeave: boolean;
  isRecord: boolean;
  isToday: boolean;
  isWorkingDay: boolean;
  presenceMinutes: number | null;
}

export interface MonthStats {
  recordedDays: number;
  present: number;
  late: number;
  absent: number;
  earlyLeave: number;
  rate: number | null;
  avgArrival: string | null;
  avgPresenceMinutes: number | null;
  /** O'tgan (bugun bilan) ish kunlaridan yozuvi yo'qlari. */
  missingWorkDays: number;
}

/** Serverdagi standart (1 — dushanba ... 6 — shanba); javob kelguncha ishlatiladi. */
export const DEFAULT_WORKING_WEEKDAYS = [1, 2, 3, 4, 5, 6];

export const CELL_STATUS_LABEL: Record<CellStatus, string> = {
  keldi: 'Keldi',
  kech_keldi: 'Kech keldi',
  kelmadi: 'Kelmadi',
  dam_olish: 'Dam olish',
  malumot_yoq: "Ma'lumot yo'q",
  kelajak: 'Kelajak kun',
};

export const CELL_STATUS_TONE: Record<CellStatus, 'green' | 'amber' | 'red' | 'slate'> = {
  keldi: 'green',
  kech_keldi: 'amber',
  kelmadi: 'red',
  dam_olish: 'slate',
  malumot_yoq: 'slate',
  kelajak: 'slate',
};

const SHORT_MONTHS = ['Yan', 'Fev', 'Mar', 'Apr', 'May', 'Iyn', 'Iyl', 'Avg', 'Sen', 'Okt', 'Noy', 'Dek'];

const KEY_STEPS: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };

export function monthOf(isoDate: string): string {
  return isoDate.slice(0, 7);
}

export function isValidMonth(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split('-').map(Number);
  const index = year * 12 + monthNumber - 1 + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`;
}

/** "Sentabr 2026" */
export function monthLabel(month: string): string {
  const [year, monthNumber] = month.split('-').map(Number);
  const name = UZ_MONTHS[monthNumber - 1];
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${year}`;
}

/** "Sen"; iyun/iyul — "Iyn"/"Iyl", uch harf bir xil bo'lib qolmasin. */
export function shortMonthLabel(month: string): string {
  return SHORT_MONTHS[Number(month.slice(5, 7)) - 1];
}

/** "15-sentabr 2026, seshanba" */
export function dayLabel(isoDate: string): string {
  const date = parseIsoDate(isoDate);
  const weekday = UZ_WEEKDAYS[(date.getUTCDay() + 6) % 7].toLowerCase();
  return `${date.getUTCDate()}-${UZ_MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${weekday}`;
}

/** "09:03" yoki "09:03:12" — kun boshidan beri daqiqalar. */
export function clockToMinutes(clock: string): number {
  const [hours = 0, minutes = 0, seconds = 0] = clock.split(':').map(Number);
  return hours * 60 + minutes + seconds / 60;
}

export function formatClock(totalMinutes: number): string {
  const rounded = Math.round(totalMinutes);
  return `${String(Math.floor(rounded / 60)).padStart(2, '0')}:${String(rounded % 60).padStart(2, '0')}`;
}

/** Kelgan va ketgan vaqt orasi (daqiqa). Biri yo'q yoki ketish kelishdan oldin bo'lsa null. */
export function presenceMinutes(checkIn?: string | null, checkOut?: string | null): number | null {
  if (!checkIn || !checkOut) return null;
  const minutes = Math.round(clockToMinutes(checkOut) - clockToMinutes(checkIn));
  return minutes > 0 ? minutes : null;
}

/** Oyning 1-kunidan oldingi bo'sh kataklar — hafta dushanbadan boshlanadi. */
export function leadingBlanks(month: string): number {
  return (parseIsoDate(`${month}-01`).getUTCDay() + 6) % 7;
}

export function buildMonthGrid(
  records: AttendanceDay[],
  month: string,
  today: string,
  workingWeekdays: number[],
): CalendarCell[] {
  const byDate = new Map(records.map((record) => [record.date, record]));
  const [year, monthNumber] = month.split('-').map(Number);
  const daysInMonth = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const cells: CalendarCell[] = [];
  for (let day = 1; day <= daysInMonth; day++) {
    const date = `${month}-${String(day).padStart(2, '0')}`;
    const isoWeekday = ((parseIsoDate(date).getUTCDay() + 6) % 7) + 1;
    const isWorkingDay = workingWeekdays.includes(isoWeekday);
    const record = byDate.get(date);
    let status: CellStatus;
    if (record) status = record.status;
    else if (date > today) status = 'kelajak';
    else status = isWorkingDay ? 'malumot_yoq' : 'dam_olish';
    cells.push({
      date,
      day,
      status,
      checkIn: record?.checkIn ?? null,
      checkOut: record?.checkOut ?? null,
      earlyLeave: Boolean(record?.earlyLeave),
      isRecord: record !== undefined,
      isToday: date === today,
      isWorkingDay,
      presenceMinutes: presenceMinutes(record?.checkIn, record?.checkOut),
    });
  }
  return cells;
}

/** Oy ko'rsatkichlari — serverdagi `_month_summary` bilan bir xil qoida
 *  (app/routers/attendance.py): dam olish sanalmaydi, yozuv bo'lmasa null. */
export function monthStats(cells: CalendarCell[]): MonthStats {
  const counted = cells.filter((cell) => cell.isRecord && cell.status !== 'dam_olish');
  const present = counted.filter((cell) => cell.status === 'keldi').length;
  const late = counted.filter((cell) => cell.status === 'kech_keldi').length;
  const attended = counted.filter((cell) => cell.status === 'keldi' || cell.status === 'kech_keldi');
  const arrivals = attended.flatMap((cell) => (cell.checkIn ? [clockToMinutes(cell.checkIn)] : []));
  const stays = attended.flatMap((cell) => (cell.presenceMinutes !== null ? [cell.presenceMinutes] : []));
  const average = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;
  return {
    recordedDays: counted.length,
    present,
    late,
    absent: counted.filter((cell) => cell.status === 'kelmadi').length,
    earlyLeave: counted.filter((cell) => cell.earlyLeave).length,
    rate: counted.length ? Math.round(((present + late) * 1000) / counted.length) / 10 : null,
    avgArrival: arrivals.length ? formatClock(average(arrivals)) : null,
    avgPresenceMinutes: stays.length ? Math.round(average(stays)) : null,
    missingWorkDays: cells.filter((cell) => cell.status === 'malumot_yoq').length,
  };
}

/** Kalendarda strelka bosilganda fokus o'tadigan sana; boshqa tugma — null. */
export function keyboardTarget(date: string, key: string): string | null {
  const step = KEY_STEPS[key];
  return step === undefined ? null : addDays(date, step);
}
