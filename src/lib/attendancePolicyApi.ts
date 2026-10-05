import { DAY_START_HOUR } from './uzDate';
import { api, type CallOptions } from './apiClient';

/** Kelib-ketish qoidalari (camera-api/app/routers/attendance_policy.py). */
export interface AttendancePolicy {
  staffStart: string;
  studentStart: string;
  graceMinutes: number;
  workEnd: string;
  /** ISO hafta kunlari: 1 — dushanba ... 7 — yakshanba. */
  workDays: number[];
  trackLastSeen: boolean;
  staffLateAfter: string;
  studentLateAfter: string;
  recomputed?: number;
}

export type AttendancePolicyInput = Omit<AttendancePolicy, 'staffLateAfter' | 'studentLateAfter' | 'recomputed'>;

/** `opts` — sahifa yopilganda so'rovni bekor qilish uchun (AbortSignal):
 *  ilgari uni uzatib bo'lmasdi va javob komponent o'chgandan keyin kelardi. */
export function getAttendancePolicy(token: string | null, opts: CallOptions = {}) {
  return api.get<AttendancePolicy>('/api/attendance-policy', token, opts);
}

export function saveAttendancePolicy(token: string | null, body: AttendancePolicyInput) {
  return api.put<AttendancePolicy>('/api/attendance-policy', body, token);
}

/** Bayram / qo'shimcha dam olish kuni. */
export interface Holiday {
  date: string;
  name: string;
  recomputed?: number;
}

export function listHolidays(token: string | null, year: number, opts: CallOptions = {}) {
  return api.get<Holiday[]>(`/api/attendance-policy/holidays?year=${year}`, token, opts);
}

export function addHoliday(token: string | null, body: { date: string; name: string }) {
  return api.post<Holiday>('/api/attendance-policy/holidays', body, token);
}

export function addStandardHolidays(token: string | null, year: number) {
  return api.post<{ added: number; recomputed: number }>(`/api/attendance-policy/holidays/standart?year=${year}`, {}, token);
}

export function deleteHoliday(token: string | null, date: string) {
  return api.del(`/api/attendance-policy/holidays/${date}`, token);
}

const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** "08:00" -> 480. Vaqt noto'g'ri bo'lsa null. */
export function minutesOfDay(hhmm: string): number | null {
  const match = TIME_RE.exec((hhmm ?? '').trim());
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

/** "08:00" + 10 -> "08:10". Vaqt bo'sh yoki noto'g'ri bo'lsa "—"
 *  (ilgari "NaN:NaN" chiqardi: `type="time"` maydoni tozalanganda
 *  qiymat bo'sh satr bo'ladi va "Qanday hisoblanadi" kartasi buzilardi). */
export function addMinutes(hhmm: string, minutes: number): string {
  const base = minutesOfDay(hhmm);
  if (base === null || !Number.isFinite(minutes)) return '—';
  const total = (((base + minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export type AttendancePolicyErrors = Partial<Record<keyof AttendancePolicyInput, string>>;

/**
 * Saqlashdan OLDINGI tekshiruv. Ilgari bu yerda hech narsa yo'q edi:
 * bo'sh vaqt maydoni yoki bitta ham belgilanmagan ish kuni serverga
 * ketib, javobida pydantic'ning inglizcha xatosi qaytardi
 * ("Input should be in a valid time format") — foydalanuvchi qaysi
 * maydon aybdorligini ham bilmasdi.
 */
export function validateAttendancePolicy(form: AttendancePolicyInput): AttendancePolicyErrors {
  const errors: AttendancePolicyErrors = {};
  const staff = minutesOfDay(form.staffStart);
  const student = minutesOfDay(form.studentStart);
  const end = minutesOfDay(form.workEnd);

  if (staff === null) errors.staffStart = "Ish boshlanish vaqtini kiriting (masalan 08:30)";
  if (student === null) errors.studentStart = "Dars boshlanish vaqtini kiriting (masalan 08:30)";
  // Ish kuni 06:00 da almashadi: undan oldingi boshlanish kechagi kunga tushadi.
  const dayStart = DAY_START_HOUR * 60;
  if (staff !== null && staff < dayStart) errors.staffStart = `Ish ${DAY_START_HOUR}:00 dan oldin boshlana olmaydi — kun ${DAY_START_HOUR}:00 da almashadi`;
  if (student !== null && student < dayStart) errors.studentStart = `Dars ${DAY_START_HOUR}:00 dan oldin boshlana olmaydi — kun ${DAY_START_HOUR}:00 da almashadi`;
  if (end === null) errors.workEnd = "Ish tugash vaqtini kiriting (masalan 17:00)";

  if (!Number.isInteger(form.graceMinutes) || form.graceMinutes < 0 || form.graceMinutes > 180) {
    errors.graceMinutes = "0 dan 180 gacha daqiqa kiriting";
  }
  if (form.workDays.length === 0) {
    errors.workDays = "Kamida bitta ish kunini belgilang — aks holda hech kim kech kelgan hisoblanmaydi";
  }
  // Server ham tekshiradi (attendance_policy.py), lekin xabari bitta
  // maydonga bog'lanmagan — bu yerda aniq maydon ko'rsatiladi.
  if (staff !== null && end !== null && end <= staff) {
    errors.workEnd = "Ish tugashi xodimlar ish boshlanishidan keyin bo'lishi kerak";
  } else if (student !== null && end !== null && end <= student) {
    errors.workEnd = "Ish tugashi dars boshlanishidan keyin bo'lishi kerak";
  }
  /* Kechikish chegarasi ish tugashidan keyinga tushib qolmasin.
     Masalan 08:00 boshlanish + 600 daqiqa emas, 16:00 boshlanish + 120
     daqiqa: chegara 18:00 bo'ladi-yu, ish 17:00 da tugaydi — o'sha kuni
     kelgan HAMMA "o'z vaqtida" bo'lib qoladi va kechikish hisobi
     jimgina o'chib qoladi. Server buni tekshirmaydi. */
  if (!errors.graceMinutes && end !== null) {
    const limit = Math.max(staff ?? -1, student ?? -1);
    if (limit >= 0 && limit + form.graceMinutes >= end) {
      errors.graceMinutes =
        "Kechikish chegarasi ish tugashidan keyinga o'tib ketdi — hech kim kech kelgan hisoblanmaydi";
    }
  }
  return errors;
}
