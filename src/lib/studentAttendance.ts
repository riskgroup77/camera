/**
 * Talabalar davomati sahifalari (/talabalar, fakultet, guruh, /shaxs) uchun
 * sof yordamchi funksiyalar — React'siz, testlanadi
 * (studentAttendance.test.ts). Ma'lumot shakli: lib/situationApi.ts.
 */
import type { ProgressSegment, Tone } from '../ui';
import { addDays } from './uzDate';
import type {
  AttendanceStatus,
  CalendarDay,
  CourseBlock,
  Counts,
  GroupStat,
  GroupStudent,
  Lesson,
  LessonAttendanceStatus,
  PersonVisit,
  TeacherStatus,
} from './situationApi';

// ───────────────────────────────────────────── Holatlar

export const STATUS_META: Record<AttendanceStatus, { label: string; short: string; tone: Tone }> = {
  keldi: { label: 'Keldi', short: 'Keldi', tone: 'success' },
  kech_keldi: { label: 'Kech keldi', short: 'Kech', tone: 'warning' },
  kelmadi: { label: 'Kelmadi', short: 'Kelmadi', tone: 'danger' },
  kutilmoqda: { label: 'Hali kelmagan', short: 'Kutilmoqda', tone: 'neutral' },
  malumot_yoq: { label: "Ma'lumot yo'q", short: "Ma'lumot yo'q", tone: 'neutral' },
  dam_olish: { label: 'Dam olish', short: 'Dam olish', tone: 'neutral' },
};

/** Noma'lum satr kelsa ham yiqilmaydi. */
export function statusMeta(status: string | null | undefined) {
  return STATUS_META[(status ?? 'malumot_yoq') as AttendanceStatus] ?? STATUS_META.malumot_yoq;
}

export function isPresent(status: AttendanceStatus): boolean {
  return status === 'keldi' || status === 'kech_keldi';
}

/** Hali kelmagan / kelmagan — setkada surat kulrang ko'rinadi. */
export function isAwaiting(status: AttendanceStatus): boolean {
  return status === 'kelmadi' || status === 'kutilmoqda';
}

const BIOMETRICS: Record<string, { label: string; tone: 'success' | 'warning' | 'neutral' }> = {
  tasdiqlangan: { label: 'Yuzi tasdiqlangan', tone: 'success' },
  kutilmoqda: { label: 'Yuzi kutilmoqda', tone: 'warning' },
  yoq: { label: "Yuzi yo'q", tone: 'neutral' },
};

export function biometricsMeta(status: string | null | undefined) {
  return BIOMETRICS[status ?? 'yoq'] ?? BIOMETRICS.yoq;
}

// ───────────────────────────────────────────── Counts

export const EMPTY_COUNTS: Counts = {
  total: 0,
  enrolled: 0,
  present: 0,
  late: 0,
  absent: 0,
  dayOff: 0,
  notYet: 0,
  noData: 0,
  rate: null,
};

/** Serverdagi qoida: present / (present + absent + notYet) * 100, bir xona. */
export function computeRate(present: number, absent: number, notYet: number): number | null {
  const base = present + absent + notYet;
  if (base <= 0) return null;
  return Math.round((present * 1000) / base) / 10;
}

export function sumCounts(list: readonly Counts[]): Counts {
  const sum = { ...EMPTY_COUNTS };
  for (const c of list) {
    sum.total += c.total;
    sum.enrolled += c.enrolled;
    sum.present += c.present;
    sum.late += c.late;
    sum.absent += c.absent;
    sum.dayOff += c.dayOff;
    sum.notYet += c.notYet;
    sum.noData += c.noData;
  }
  sum.rate = computeRate(sum.present, sum.absent, sum.notYet);
  return sum;
}

/** Talabalar ro'yxatidan Counts (jonli yangilanishdan keyin qayta hisoblash uchun). */
export function countsFromStudents(students: readonly Pick<GroupStudent, 'status' | 'biometricsStatus'>[]): Counts {
  const c = { ...EMPTY_COUNTS };
  for (const s of students) {
    c.total += 1;
    if (s.biometricsStatus === 'tasdiqlangan') c.enrolled += 1;
    if (isPresent(s.status)) c.present += 1;
    if (s.status === 'kech_keldi') c.late += 1;
    else if (s.status === 'kelmadi') c.absent += 1;
    else if (s.status === 'dam_olish') c.dayOff += 1;
    else if (s.status === 'kutilmoqda') c.notYet += 1;
    else if (s.status === 'malumot_yoq') c.noData += 1;
  }
  c.rate = computeRate(c.present, c.absent, c.notYet);
  return c;
}

/** Bitta chiziqda holatlar ulushi: vaqtida / kech / kelmadi / kutilmoqda / ma'lumot yo'q. */
export function countSegments(counts: Counts): ProgressSegment[] {
  return [
    { value: Math.max(0, counts.present - counts.late), tone: 'success', label: 'Keldi' },
    { value: counts.late, tone: 'warning', label: 'Kech keldi' },
    { value: counts.absent, tone: 'danger', label: 'Kelmadi' },
    { value: counts.notYet, tone: 'neutral', label: 'Hali kelmagan' },
    { value: counts.noData, tone: 'neutral', label: "Ma'lumot yo'q" },
    // Dam olish kuni — o'lchanmagan emas, o'lchanishi SHART BO'LMAGAN kun.
    // Ikkovini bitta segmentga qo'shish "ma'lumot yo'q" ni sun'iy kattalashtirardi.
    { value: counts.dayOff, tone: 'neutral', label: 'Dam olish' },
  ];
}

/** Counts → holat bo'yicha sonlar (setka filtrlari bilan bir xil kalitlar). */
export function countsByStatus(counts: Counts): Record<AttendanceStatus, number> {
  return {
    keldi: Math.max(0, counts.present - counts.late),
    kech_keldi: counts.late,
    kelmadi: counts.absent,
    kutilmoqda: counts.notYet,
    malumot_yoq: counts.noData,
    dam_olish: counts.dayOff,
  };
}

// ───────────────────────────────────────────── Guruhlar

export type GroupSortKey = 'rate-asc' | 'rate-desc' | 'name';

/** Guruhlarni saralash; foizi yo'qlar (null) doim oxirida. */
export function sortGroups<T extends Pick<GroupStat, 'name' | 'rate'>>(groups: readonly T[], key: GroupSortKey): T[] {
  const byName = (a: T, b: T) => a.name.localeCompare(b.name, 'uz', { numeric: true });
  if (key === 'name') return [...groups].sort(byName);
  const dir = key === 'rate-asc' ? 1 : -1;
  return [...groups].sort((a, b) => {
    if (a.rate === null && b.rate === null) return byName(a, b);
    if (a.rate === null) return 1;
    if (b.rate === null) return -1;
    return (a.rate - b.rate) * dir || byName(a, b);
  });
}

export function courseLabel(course: number | null): string {
  return course ? `${course}-kurs` : "Kurs ko'rsatilmagan";
}

/** Tekis guruhlar ro'yxatidan kurs bloklari ("Fakultetsiz" sahifasi uchun —
 *  server faqat uuid fakultet uchun bloklab beradi). */
export function groupsToCourses(groups: readonly GroupStat[]): CourseBlock[] {
  const byCourse = new Map<number | null, GroupStat[]>();
  for (const g of groups) {
    const list = byCourse.get(g.course) ?? [];
    list.push(g);
    byCourse.set(g.course, list);
  }
  return [...byCourse.entries()]
    .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : a - b))
    .map(([course, list]) => ({
      course,
      label: courseLabel(course),
      groups: sortGroups(list, 'name'),
      totals: sumCounts(list),
    }));
}

// ───────────────────────────────────────────── Talabalar setkasi

export type StudentFilter = 'all' | AttendanceStatus;
export type StudentSort = 'name' | 'status' | 'arrival';

/** Katta-kichik harf, apostrof turlari (' ʻ ʼ `) va ortiqcha bo'shliqlarsiz. */
export function normalizeText(value: string): string {
  return value
    .toLocaleLowerCase('uz')
    .replace(/[‘’ʻʼ`']/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

/** Plitkadagi son bilan bir xil bo'lishi uchun: "Ma'lumot yo'q" plitkasi
 *  `noData + dayOff` ni ko'rsatadi, demak filtri ham ikkalasini oladi
 *  (aks holda "Ma'lumot yo'q: 5" bosilganda setkada 3 ta talaba chiqardi). */
export function matchesFilter(status: AttendanceStatus, filter: StudentFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'malumot_yoq') return status === 'malumot_yoq' || status === 'dam_olish';
  return status === filter;
}

export function filterStudents<T extends Pick<GroupStudent, 'fullName' | 'status'>>(
  students: readonly T[],
  filter: StudentFilter,
  query: string,
): T[] {
  const needle = normalizeText(query);
  return students.filter(
    (s) => matchesFilter(s.status, filter) && (!needle || normalizeText(s.fullName).includes(needle)),
  );
}

/** "Holat bo'yicha" — kelmaganlar birinchi (devor ekranida kimga e'tibor
 *  kerakligi darhol ko'rinadi); "Kelish vaqti" — erta kelganlar birinchi. */
const ATTENTION_ORDER: Record<AttendanceStatus, number> = {
  kelmadi: 0,
  kutilmoqda: 1,
  kech_keldi: 2,
  keldi: 3,
  malumot_yoq: 4,
  dam_olish: 5,
};

export function sortStudents<T extends Pick<GroupStudent, 'fullName' | 'status' | 'checkIn'>>(
  students: readonly T[],
  sort: StudentSort,
): T[] {
  const byName = (a: T, b: T) => a.fullName.localeCompare(b.fullName, 'uz');
  if (sort === 'name') return [...students].sort(byName);
  if (sort === 'status') {
    return [...students].sort((a, b) => ATTENTION_ORDER[a.status] - ATTENTION_ORDER[b.status] || byName(a, b));
  }
  return [...students].sort((a, b) => {
    // Server "9:05" ko'rinishida ham qaytarishi mumkin — satrlarni solishtirsak
    // "9:05" > "10:05" chiqib, kech kelgan talaba ro'yxat boshiga tushardi.
    // Shuning uchun daqiqaga o'girib solishtiriladi.
    const am = clockMinutes(toClock(a.checkIn));
    const bm = clockMinutes(toClock(b.checkIn));
    if (am !== null && bm !== null) return am - bm || byName(a, b);
    if (am !== null) return -1;
    if (bm !== null) return 1;
    return ATTENTION_ORDER[a.status] - ATTENTION_ORDER[b.status] || byName(a, b);
  });
}

/** WebSocket "attendance_recorded" xabarini setkaga qo'llash. Talaba bu
 *  guruhda bo'lmasa yoki holati o'zgarmasa — o'sha massiv qaytadi. */
export function applyArrival<T extends GroupStudent>(
  students: readonly T[],
  arrival: { personId: string; status: 'keldi' | 'kech_keldi'; checkIn: string | null },
): readonly T[] {
  const index = students.findIndex((s) => s.id === arrival.personId);
  if (index < 0) return students;
  const current = students[index];
  const checkIn = arrival.checkIn ?? current.checkIn;
  if (current.status === arrival.status && current.checkIn === checkIn) return students;
  const next = [...students];
  next[index] = { ...current, status: arrival.status, checkIn };
  return next;
}

// ───────────────────────────────────────────── Darslar

export const TEACHER_STATUS_META: Record<TeacherStatus, { label: string; tone: Tone }> = {
  oz_vaqtida: { label: "O'z vaqtida", tone: 'success' },
  kechikdi: { label: 'Kech keldi', tone: 'warning' },
  kelmadi: { label: 'Kelmadi', tone: 'danger' },
  kutilmoqda: { label: 'Kutilmoqda', tone: 'neutral' },
  nomalum: { label: "Noma'lum", tone: 'neutral' },
};

export const LESSON_STATE_META: Record<Lesson['state'], { label: string; tone: Tone }> = {
  upcoming: { label: 'Boshlanmagan', tone: 'neutral' },
  ongoing: { label: 'Davom etmoqda', tone: 'primary' },
  finished: { label: 'Tugagan', tone: 'neutral' },
};

export const LESSON_ATTENDANCE_META: Record<LessonAttendanceStatus, { label: string; tone: Tone }> = {
  keldi: { label: 'Qatnashdi', tone: 'success' },
  kech_keldi: { label: 'Kech kirdi', tone: 'warning' },
  kelmadi: { label: 'Qatnashmadi', tone: 'danger' },
};

/** Darsdagi davomat foizi: yakunlangan — (keldi) / kutilgan; aks holda ko'ringanlar. */
export function lessonRate(lesson: Pick<Lesson, 'expected' | 'present' | 'seen' | 'finalized'>): number | null {
  if (lesson.expected <= 0) return null;
  const count = lesson.finalized ? lesson.present : lesson.seen;
  return Math.min(100, Math.round((count * 1000) / lesson.expected) / 10);
}

/** "09:00–10:20" yoki "Vaqt ko'rsatilmagan". */
export function lessonTime(lesson: Pick<Lesson, 'startsAt' | 'endsAt'>): string {
  if (!lesson.startsAt) return "Vaqt ko'rsatilmagan";
  return lesson.endsAt ? `${lesson.startsAt}–${lesson.endsAt}` : lesson.startsAt;
}

/** Diqqat balli (0–100) → ohang. */
export function scoreTone(score: number | null | undefined): Tone {
  if (score === null || score === undefined) return 'neutral';
  if (score >= 75) return 'success';
  if (score >= 50) return 'warning';
  return 'danger';
}

// ───────────────────────────────────────────── Vaqt

const TASHKENT_CLOCK = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Tashkent',
});

/** ISO vaqt ("2026-09-19T08:12:00+05:00") yoki "08:12[:30]" → "08:12" (Toshkent). */
export function toClock(value: string | null | undefined): string | null {
  if (!value) return null;
  const short = /^(\d{1,2}):(\d{2})/.exec(value);
  if (short) return `${short[1].padStart(2, '0')}:${short[2]}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return TASHKENT_CLOCK.format(date);
}

export function clockMinutes(clock: string | null | undefined): number | null {
  if (!clock) return null;
  const [h, m] = clock.split(':').map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

/** Trend nuqtalarining o'rtacha foizi; ma'lumotsiz (null) kunlar hisobga olinmaydi. */
export function averageRate(points: readonly { rate: number | null }[]): number | null {
  const values = points.map((p) => p.rate).filter((r): r is number => r !== null);
  if (!values.length) return null;
  return Math.round((values.reduce((s, v) => s + v, 0) / values.length) * 10) / 10;
}

// ───────────────────────────────────────────── Shaxs sahifasi

/** Oraliqdagi oylar ("YYYY-MM"), eskisi birinchi; `limit` dan oshsa — oxirgilari. */
export function monthsInRange(from: string, to: string, limit = 12): string[] {
  if (!from || !to || from > to) return [];
  const months: string[] = [];
  let [year, month] = from.slice(0, 7).split('-').map(Number);
  const [endYear, endMonth] = to.slice(0, 7).split('-').map(Number);
  while (year < endYear || (year === endYear && month <= endMonth)) {
    months.push(`${year}-${String(month).padStart(2, '0')}`);
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return months.slice(-limit);
}

/** Kelish vaqti grafigi uchun: har kun — daqiqa (kelmagan kun — null). */
export function arrivalSeries(calendar: readonly CalendarDay[]) {
  return calendar.map((day) => ({
    date: day.date,
    status: day.status,
    minutes: isPresent(day.status) ? clockMinutes(day.checkIn) : null,
    checkIn: day.checkIn,
  }));
}

/** Tashriflarni kunlarga ajratish (yangi kun birinchi, ichida — yangi tashrif birinchi). */
export function visitsByDate(visits: readonly PersonVisit[]): Array<{ date: string; visits: PersonVisit[]; minutes: number }> {
  const map = new Map<string, PersonVisit[]>();
  for (const v of visits) {
    const list = map.get(v.date) ?? [];
    list.push(v);
    map.set(v.date, list);
  }
  return [...map.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, list]) => ({
      date,
      visits: [...list].sort((a, b) => b.firstSeen.localeCompare(a.firstSeen)),
      minutes: list.reduce((sum, v) => sum + v.durationMinutes, 0),
    }));
}

/** Guruh talabasi uchun "so'nggi N kun" oralig'i (sana bilan tugaydi). */
export function recentRange(date: string, days: number): { from: string; to: string } {
  return { from: addDays(date, -(days - 1)), to: date };
}

// ───────────────────────────────────────────── Yuz topshirish (enrollment)

/** Guruh/fakultetda davomat ko'rsatish uchun yetarli yuz ulushi (%). Undan past — "Yuz topshirish" ko'rinishi. */
export const ATTENDANCE_READY_PCT = 50;

/** Yuzi tasdiqlanganlar ulushi (%), talaba yo'q → null. */
export function enrolledPct(counts: Pick<Counts, 'total' | 'enrolled'>): number | null {
  return counts.total > 0 ? Math.round((counts.enrolled / counts.total) * 1000) / 10 : null;
}

/** Davomat foizi ma'noli bo'lishi uchun yuzlar yetarlimi. */
export function hasAttendanceData(counts: Pick<Counts, 'total' | 'enrolled'>): boolean {
  const pct = enrolledPct(counts);
  return pct !== null && pct >= ATTENDANCE_READY_PCT;
}

/** Yuz topshirish progressi rangi: tugagan — yashil, yarmidan oshgan — asosiy, boshlanmagan — xavf. */
export function enrollTone(pct: number | null | undefined): Tone {
  if (pct === null || pct === undefined) return 'neutral';
  if (pct >= 90) return 'success';
  if (pct >= ATTENDANCE_READY_PCT) return 'primary';
  if (pct > 0) return 'warning';
  return 'danger';
}

export interface EnrollSnapshot {
  date: string;
  confirmed: number;
}

/** Kunlik kuzatuv (brauzerda saqlanadi): shu kun qiymatini yangilaydi, oxirgi 60 kun qoladi. */
export function recordSnapshot(list: readonly EnrollSnapshot[], date: string, confirmed: number): EnrollSnapshot[] {
  const next = list.filter((s) => s.date !== date && /^\d{4}-\d{2}-\d{2}$/.test(s.date) && Number.isFinite(s.confirmed));
  next.push({ date, confirmed });
  next.sort((a, b) => a.date.localeCompare(b.date));
  return next.slice(-60);
}

/** Ikki ISO sana orasidagi kunlar (b − a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/**
 * So'nggi `windowDays` kundagi sur'at: kuniga nechta yangi yuz tasdiqlanmoqda.
 * Kamida 1 kunlik farq kerak, aks holda null.
 */
export function enrollPace(list: readonly EnrollSnapshot[], today: string, windowDays = 14): { perDay: number; days: number } | null {
  const current = list.find((s) => s.date === today) ?? list[list.length - 1];
  if (!current) return null;
  const base = list.find((s) => daysBetween(s.date, current.date) >= 1 && daysBetween(s.date, current.date) <= windowDays);
  if (!base) return null;
  const days = daysBetween(base.date, current.date);
  return { perDay: Math.max(0, (current.confirmed - base.confirmed) / days), days };
}

/** Qolganlar shu sur'atda qachon tugaydi (ISO sana) — sur'at 0 bo'lsa null. */
export function projectCompletion(remaining: number, perDay: number, today: string): string | null {
  if (remaining <= 0) return today;
  if (!(perDay > 0)) return null;
  return addDays(today, Math.ceil(remaining / perDay));
}

/** Maqsad sanasigacha har kuni nechta yuz kerak (sana o'tgan/bugun → qolganlarning hammasi). */
export function neededPerDay(remaining: number, today: string, target: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(target)) return null;
  if (remaining <= 0) return 0;
  const days = daysBetween(today, target);
  return days <= 0 ? remaining : Math.ceil(remaining / days);
}

// ───────────────────────────────────────────── Shaxs KPI (xodim)

/** Kechikish chegarasi standarti — attendance_policy: 08:00 + 10 daqiqa.
 *  Haqiqiy qiymat /api/attendance-policy dan olinadi (lateAfterMinutes). */
export const LATE_CUTOFF_MINUTES = 8 * 60 + 10;

/** "08:10" -> 490; noto'g'ri qiymat -> standart chegara. */
export function lateAfterMinutes(hhmm: string | null | undefined): number {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm ?? '');
  return m ? Number(m[1]) * 60 + Number(m[2]) : LATE_CUTOFF_MINUTES;
}

export interface PersonKpis {
  rate: number | null;
  avgArrivalMinutes: number | null;
  presentDays: number;
  lateDays: number;
  absentDays: number;
  /** O'z vaqtida kelgan (kechikmagan) uzluksiz kunlar — oxiridan hisoblanadi; dam olish/ma'lumotsiz kunlar uzmaydi. */
  onTimeStreak: number;
  punctualPct: number | null;
}

export function personKpis(calendar: readonly CalendarDay[]): PersonKpis {
  let present = 0;
  let late = 0;
  let absent = 0;
  const arrivals: number[] = [];
  for (const d of calendar) {
    if (d.status === 'keldi' || d.status === 'kech_keldi') {
      present++;
      if (d.status === 'kech_keldi') late++;
      const m = clockMinutes(d.checkIn);
      if (m !== null) arrivals.push(m);
    } else if (d.status === 'kelmadi') absent++;
  }
  let streak = 0;
  for (let i = calendar.length - 1; i >= 0; i--) {
    const s = calendar[i].status;
    if (s === 'keldi') streak++;
    else if (s === 'kech_keldi' || s === 'kelmadi') break;
  }
  return {
    rate: present + absent > 0 ? Math.round((present / (present + absent)) * 1000) / 10 : null,
    avgArrivalMinutes: arrivals.length ? Math.round(arrivals.reduce((a, b) => a + b, 0) / arrivals.length) : null,
    presentDays: present,
    lateDays: late,
    absentDays: absent,
    onTimeStreak: streak,
    punctualPct: present > 0 ? Math.round(((present - late) / present) * 1000) / 10 : null,
  };
}

export interface WeekdayStat {
  weekday: number; // 1=Du … 6=Sha
  label: string;
  days: number;
  present: number;
  late: number;
  absent: number;
  avgArrivalMinutes: number | null;
}

const WEEKDAY_LABELS = ['Du', 'Se', 'Cho', 'Pa', 'Ju', 'Sha'];

/** Hafta kunlari bo'yicha naqsh (yakshanbasiz). */
export function weekdayPattern(calendar: readonly CalendarDay[]): WeekdayStat[] {
  const rows = WEEKDAY_LABELS.map((label, i) => ({ weekday: i + 1, label, days: 0, present: 0, late: 0, absent: 0, sum: 0, n: 0 }));
  for (const d of calendar) {
    const wd = new Date(`${d.date}T00:00:00Z`).getUTCDay(); // 0=Ya
    if (wd === 0) continue;
    const r = rows[wd - 1];
    if (d.status === 'keldi' || d.status === 'kech_keldi') {
      r.days++;
      r.present++;
      if (d.status === 'kech_keldi') r.late++;
      const m = clockMinutes(d.checkIn);
      if (m !== null) {
        r.sum += m;
        r.n++;
      }
    } else if (d.status === 'kelmadi') {
      r.days++;
      r.absent++;
    }
  }
  return rows.map(({ sum, n, ...r }) => ({ ...r, avgArrivalMinutes: n ? Math.round(sum / n) : null }));
}

/** Oldingi, xuddi shu uzunlikdagi davr. */
export function previousRange(from: string, to: string): { from: string; to: string } {
  const len = daysBetween(from, to) + 1;
  return { from: addDays(from, -len), to: addDays(from, -1) };
}
