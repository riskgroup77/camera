/** O'zbekcha sana yordamchilari. Sanalar "YYYY-MM-DD" satr sifatida
 *  yuritiladi va UTC yarim tunidagi Date bilan hisoblanadi — brauzer
 *  mintaqasi Toshkentdan farq qilsa ham kun siljimaydi. */

export const UZ_MONTHS = [
  'yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
  'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr',
];
export const UZ_WEEKDAYS = ['Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba', 'Yakshanba'];
export const UZ_WEEKDAYS_SHORT = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'];

const TASHKENT = 'Asia/Tashkent';

/** Ish kuni shu soatda (Toshkent vaqti) almashadi — backenddagi
 *  settings.day_start_hour bilan bir xil (camera-api/app/timezone.py). */
export const DAY_START_HOUR = 6;

/** Toshkent bo'yicha bugungi ISH KUNI — 06:00 gacha kechagi kun davom etadi.
 *  Brauzer soat mintaqasiga bog'liq emas. */
export function todayInTashkent(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: TASHKENT,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(now.getTime() - DAY_START_HOUR * 3_600_000));
}

/** Toshkent bo'yicha KALENDAR sanasi (06:00 siljishisiz) — vaqt
 *  belgisini "bugun 12:05" ko'rinishida qisqartirish uchun. */
export function calendarDateInTashkent(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: TASHKENT,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

export function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  const date = parseIsoDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return toIsoDate(date);
}

export function daysBetweenInclusive(from: string, to: string): number {
  return Math.round((parseIsoDate(to).getTime() - parseIsoDate(from).getTime()) / 86_400_000) + 1;
}

/* -------------------------------------------------------------------
 * Oy ("YYYY-MM") — oylik tabel uchun. Sana kabi satr bilan yuritiladi.
 * ----------------------------------------------------------------- */

export function isMonth(value: string | null | undefined): value is string {
  return Boolean(value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value));
}

/** Sanadan oy: "2026-09-19" → "2026-09". */
export function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

/** "2026-09" → "Sentabr 2026". */
export function formatUzMonth(month: string): string {
  if (!isMonth(month)) return month;
  const name = UZ_MONTHS[Number(month.slice(5, 7)) - 1];
  return `${name[0].toUpperCase()}${name.slice(1)} ${month.slice(0, 4)}`;
}

/** Oydagi kunlar soni. */
export function daysInMonth(month: string): number {
  if (!isMonth(month)) return 0;
  return new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).getUTCDate();
}

/** Oy va kun → hafta kuni indeksi (0 = dushanba). */
export function weekdayIndex(month: string, day: number): number {
  const date = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, day));
  return (date.getUTCDay() + 6) % 7;
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString('ru-RU');
}

/** "hozirgina", "12 daq oldin", "3 soat oldin", "2 kun oldin" — bir haftadan
 *  eskisi sana bilan. Kelajakdagi vaqt (soat farqi) "hozirgina" deb olinadi. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(seconds)) return '';
  if (seconds < 45) return 'hozirgina';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} daq oldin`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} soat oldin`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} kun oldin`;
  return iso.slice(0, 10);
}

/** Davomiylik: 45 -> "45 daq", 150 -> "2,5 soat", 4320 -> "3 kun". */
export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—';
  if (minutes < 1) return '1 daq dan kam';
  if (minutes < 60) return `${Math.round(minutes)} daq`;
  const hours = minutes / 60;
  if (hours < 48) return `${(Math.round(hours * 10) / 10).toString().replace('.', ',')} soat`;
  return `${Math.round(hours / 24)} kun`;
}
