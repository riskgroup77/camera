/**
 * Kelish oqimi grafigi (Nazorat → "Institut — talabalar, jonli") uchun sof
 * hisoblar: soatlik ustunlar, ko'rinadigan oraliq, vaqt bo'yicha o'rin.
 *
 * Manba — /api/situation/overview `arrivalsByHour`: har soatda nechta odam
 * kunning BIRINCHI ko'rinishini bergan va shundan nechtasi "kech_keldi"
 * yozuvi (hisobot va kartochkalar bilan bitta qoida).
 */

import type { PersonType } from './situationApi';

export interface HourBucket {
  hour: number;
  students: number;
  staff: number;
  studentsLate?: number;
  staffLate?: number;
}

export interface ArrivalBar {
  hour: number;
  total: number;
  /** "kech_keldi" — kechikish chegarasidan keyin kelganlar. */
  late: number;
  onTime: number;
}

/** Ish kuni grafigi kamida shu soatdan boshlanadi (bo'sh erta soatlar ko'rsatilmaydi). */
export const DAY_START_HOUR = 7;
/** Bugun "hozir"gacha chiziladi, lekin kechqurun bo'sh soatlar ustunlarni
 *  siqib qo'ymasligi uchun shu soatdan keyin faqat kelish bo'lsa davom etadi. */
export const DAY_END_HOUR = 18;

export function arrivalBars(buckets: readonly HourBucket[], who: PersonType): ArrivalBar[] {
  return buckets.map((b) => {
    const total = Math.max(0, who === 'xodim' ? b.staff : b.students);
    const late = Math.min(total, Math.max(0, (who === 'xodim' ? b.staffLate : b.studentsLate) ?? 0));
    return { hour: b.hour, total, late, onTime: total - late };
  });
}

/**
 * Ko'rsatiladigan soatlar: 07:00 (yoki undan oldingi birinchi kelish) dan
 * bugun uchun — hozirgi soatgacha (18:00 dan keyin — faqat kelish bo'lsa),
 * o'tgan kun uchun — oxirgi kelishgacha. Ortidagi bo'sh soatlar kichik
 * ustunlarni siqib qo'ymasin. Hech kim kelmagan — bo'sh ro'yxat (izoh).
 */
export function visibleBars(bars: readonly ArrivalBar[], opts: { isToday: boolean; nowHour: number }): ArrivalBar[] {
  const withData = bars.filter((b) => b.total > 0);
  if (withData.length === 0) return [];
  const byHour = new Map(bars.map((b) => [b.hour, b]));
  const first = Math.min(DAY_START_HOUR, ...withData.map((b) => b.hour));
  const lastData = Math.max(...withData.map((b) => b.hour));
  const last = Math.min(23, opts.isToday ? Math.max(lastData, Math.min(opts.nowHour, DAY_END_HOUR)) : lastData);
  const out: ArrivalBar[] = [];
  for (let hour = first; hour <= Math.max(first, last); hour += 1) {
    out.push(byHour.get(hour) ?? { hour, total: 0, late: 0, onTime: 0 });
  }
  return out;
}

/** "08:10" → 490 (daqiqa); noto'g'ri qiymat — null. */
export function clockMinutes(value: string | null | undefined): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec((value ?? '').trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

/** Kun boshidan daqiqa → grafikdagi o'rin (0..1) — `bars` oralig'i ichida bo'lsa. */
export function timeFraction(minutes: number | null, bars: readonly ArrivalBar[]): number | null {
  if (minutes === null || bars.length === 0) return null;
  const start = bars[0].hour * 60;
  const end = (bars[bars.length - 1].hour + 1) * 60;
  if (minutes < start || minutes > end) return null;
  return (minutes - start) / (end - start);
}

/** Toshkent vaqtida soat va daqiqa (kun boshidan daqiqalarda). */
export function tashkentMinutes(now: Date | number): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tashkent',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(typeof now === 'number' ? new Date(now) : now);
  const hour = Number(parts.find((p) => p.type === 'hour')?.value ?? 0) % 24;
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? 0);
  return hour * 60 + minute;
}

export function formatClock(minutes: number): string {
  const h = Math.floor(minutes / 60) % 24;
  const m = minutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function hourRange(hour: number): string {
  const h = String(hour).padStart(2, '0');
  return `${h}:00–${h}:59`;
}

/** Ustun izohi (sichqoncha ustida va ekran o'quvchi uchun). */
export function barTitle(bar: ArrivalBar): string {
  if (bar.total === 0) return `${hourRange(bar.hour)} · hech kim kelmagan`;
  const tail = bar.late > 0 ? `, shundan ${bar.late} tasi kech` : ', hammasi o‘z vaqtida';
  return `${hourRange(bar.hour)} · ${bar.total} kishi keldi${tail}`;
}

/** Guruh talabalaridan soatlik ustunlar (chapdagi jadval bilan bir xil
 *  ma'lumot): kelish vaqti soati bo'yicha, "kech_keldi" — kech qismi.
 *  Kelgan, lekin vaqti yo'qlar — `untimed`. */
export function bucketsFromPeople(people: readonly { checkIn: string | null; status: string }[]): {
  buckets: HourBucket[];
  untimed: number;
} {
  const byHour = new Map<number, HourBucket>();
  let untimed = 0;
  for (const person of people) {
    if (person.status !== 'keldi' && person.status !== 'kech_keldi') continue;
    const minutes = clockMinutes(person.checkIn);
    if (minutes === null) {
      untimed += 1;
      continue;
    }
    const hour = Math.floor(minutes / 60);
    const bucket = byHour.get(hour) ?? { hour, students: 0, staff: 0, studentsLate: 0, staffLate: 0 };
    bucket.students += 1;
    if (person.status === 'kech_keldi') bucket.studentsLate = (bucket.studentsLate ?? 0) + 1;
    byHour.set(hour, bucket);
  }
  return { buckets: [...byHour.values()].sort((a, b) => a.hour - b.hour), untimed };
}
