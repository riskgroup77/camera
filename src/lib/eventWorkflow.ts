import type { AIEvent, EventStatus } from '../types';
import { formatMinutes } from './uzDate';

/** Hodisa ish jarayoni qoidalari — app/services/event_status.py bilan
 *  AYNAN bir xil bo'lishi shart (server baribir tekshiradi, bu yerda faqat
 *  mumkin bo'lmagan tugmani ko'rsatmaslik uchun). */

/** Qaror kutayotganlar: SLA muddati va eskalatsiya shularga tegishli. */
export const OPEN_STATUSES: readonly EventStatus[] = ['yangi', 'jarayonda'];

export const STATUS_TRANSITIONS: Record<EventStatus, readonly EventStatus[]> = {
  yangi: ['jarayonda', 'tasdiqlangan', 'rad_etilgan', 'hal_qilindi'],
  jarayonda: ['yangi', 'tasdiqlangan', 'rad_etilgan', 'hal_qilindi'],
  tasdiqlangan: ['jarayonda', 'rad_etilgan', 'hal_qilindi'],
  rad_etilgan: ['jarayonda', 'tasdiqlangan'],
  hal_qilindi: ['jarayonda', 'tasdiqlangan', 'rad_etilgan'],
};

export function isOpenStatus(status: EventStatus): boolean {
  return OPEN_STATUSES.includes(status);
}

export function canTransition(from: EventStatus, to: EventStatus): boolean {
  return STATUS_TRANSITIONS[from]?.includes(to) ?? false;
}

/** Tayinlash faqat hali yopilmagan hodisaga (server ham shuni tekshiradi). */
export function canAssign(event: Pick<AIEvent, 'status' | 'isTrial'>): boolean {
  return !event.isTrial && event.status !== 'rad_etilgan' && event.status !== 'hal_qilindi';
}

export interface StatusAction {
  target: EventStatus;
  label: string;
  /** Tugma ko'rinishi: asosiy (to'q), xavfli emas, oddiy. */
  variant: 'primary' | 'success' | 'neutral';
  /** Yechim izohi so'raladi (hal_qilindi). */
  needsNote: boolean;
}

const ACTION_LABEL: Record<EventStatus, string> = {
  yangi: 'Navbatga qaytarish',
  jarayonda: 'Ishga olish',
  tasdiqlangan: 'Tasdiqlash',
  rad_etilgan: "Rad etish (yolg'on)",
  hal_qilindi: 'Hal qilindi',
};

// Tugmalar tartibi: odatdagi keyingi qadam birinchi.
const ACTION_ORDER: EventStatus[] = ['jarayonda', 'tasdiqlangan', 'hal_qilindi', 'rad_etilgan', 'yangi'];

/** Hozirgi holatdan mumkin bo'lgan amallar. Yopilgan hodisada "jarayonda"
 *  — "Qayta ochish". */
export function statusActions(status: EventStatus): StatusAction[] {
  return ACTION_ORDER.filter((target) => canTransition(status, target)).map((target) => ({
    target,
    label: target === 'jarayonda' && !isOpenStatus(status) ? 'Qayta ochish' : ACTION_LABEL[target],
    variant: target === 'hal_qilindi' ? 'success' : target === 'tasdiqlangan' ? 'primary' : 'neutral',
    needsNote: target === 'hal_qilindi',
  }));
}

export type SlaState = 'none' | 'ok' | 'soon' | 'overdue';

export interface SlaInfo {
  state: SlaState;
  /** Qolgan daqiqa (manfiy — o'tib ketgan). */
  minutesLeft: number | null;
  label: string;
}

/** Shuncha daqiqa qolganda "tez orada" (sariq) ko'rinadi. */
export const SLA_SOON_MINUTES = 10;

/** SLA holati: muddat faqat qaror kutayotgan hodisalarga tegishli. */
export function slaInfo(event: Pick<AIEvent, 'status' | 'dueAt'>, now: Date = new Date()): SlaInfo {
  if (!event.dueAt || !isOpenStatus(event.status)) return { state: 'none', minutesLeft: null, label: '' };
  const due = new Date(event.dueAt).getTime();
  if (Number.isNaN(due)) return { state: 'none', minutesLeft: null, label: '' };
  const minutesLeft = (due - now.getTime()) / 60_000;
  if (minutesLeft < 0) {
    return { state: 'overdue', minutesLeft, label: `Muddati o'tgan: ${formatMinutes(-minutesLeft)}` };
  }
  return {
    state: minutesLeft <= SLA_SOON_MINUTES ? 'soon' : 'ok',
    minutesLeft,
    label: `${formatMinutes(minutesLeft)} qoldi`,
  };
}

/** WebSocket xabari mavjud hodisaning o'zgarishimi (yangi hodisa emas). */
export function isEventUpdate(message: AIEvent): boolean {
  return message.kind === 'event_updated';
}

/** Ro'yxatdagi hodisani WebSocket'dan kelgan yangi holati bilan almashtiradi.
 *  Izohlar soni xabarda bo'lmasa, avvalgisi saqlanadi. Ro'yxatda yo'q
 *  bo'lsa — o'zgarishsiz (o'sha massiv). */
export function mergeEventUpdate(rows: AIEvent[], incoming: AIEvent): AIEvent[] {
  const index = rows.findIndex((row) => row.id === incoming.id);
  if (index < 0) return rows;
  const fields: AIEvent = { ...incoming };
  delete fields.kind;
  const previous = rows[index];
  const merged: AIEvent = {
    ...previous,
    ...fields,
    commentsCount: fields.commentsCount ?? previous.commentsCount,
  };
  const next = rows.slice();
  next[index] = merged;
  return next;
}
