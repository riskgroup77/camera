import type { Tone } from './tones';

/** Kunlik davomat holati (talaba yoki o'qituvchi). */
export type AttendanceStatus =
  | 'keldi'
  | 'kech_keldi'
  | 'kelmadi'
  | 'sababli'
  | 'kutilmoqda'
  | 'dam_olish'
  | 'nomalum';

export const ATTENDANCE_STATUS: Record<AttendanceStatus, { label: string; tone: Tone }> = {
  keldi: { label: 'Keldi', tone: 'success' },
  kech_keldi: { label: 'Kech keldi', tone: 'warning' },
  kelmadi: { label: 'Kelmadi', tone: 'danger' },
  sababli: { label: 'Sababli', tone: 'info' },
  kutilmoqda: { label: 'Hali kelmagan', tone: 'neutral' },
  dam_olish: { label: 'Dam olish', tone: 'neutral' },
  nomalum: { label: "Ma'lumot yo'q", tone: 'neutral' },
};

/** Hodisa holati (src/types EventStatus bilan bir xil). */
export type EventStatusKey = 'yangi' | 'jarayonda' | 'tasdiqlangan' | 'rad_etilgan' | 'hal_qilindi';

export const EVENT_STATUS: Record<EventStatusKey, { label: string; tone: Tone }> = {
  yangi: { label: 'Yangi', tone: 'danger' },
  jarayonda: { label: 'Jarayonda', tone: 'warning' },
  tasdiqlangan: { label: 'Tasdiqlangan', tone: 'primary' },
  rad_etilgan: { label: 'Rad etilgan', tone: 'neutral' },
  hal_qilindi: { label: 'Hal qilindi', tone: 'success' },
};

/** Hodisa jiddiyligi (src/types EventSeverity bilan bir xil). */
export type SeverityKey = 'past' | "o'rta" | 'yuqori';

export const SEVERITY: Record<SeverityKey, { label: string; tone: Tone }> = {
  past: { label: 'Past', tone: 'neutral' },
  "o'rta": { label: "O'rta", tone: 'warning' },
  yuqori: { label: 'Yuqori', tone: 'danger' },
};

/** Noma'lum satr kelsa ham yiqilmaydi — "Ma'lumot yo'q" bo'ladi. */
export function attendanceMeta(status: string | null | undefined): { label: string; tone: Tone } {
  return (status && ATTENDANCE_STATUS[status as AttendanceStatus]) || ATTENDANCE_STATUS.nomalum;
}
