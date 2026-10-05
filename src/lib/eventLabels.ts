import { EVENT_STATUS, SEVERITY, TONE_SOLID, type Tone } from '../ui';
import type { AIEvent, EventStatus } from '../types';

/** Hodisa muhimligi va holati — yagona yorliqlar va ranglar.
 *  Rang va nom manbai: src/ui/status.ts (`StatusBadge kind="event" | "severity"`);
 *  bu yerda faqat matnli kontekstlar (toast, filtr, izoh) uchun qisqa kirish. */

export const SEVERITY_LABEL: Record<AIEvent['severity'], string> = {
  past: SEVERITY.past.label,
  "o'rta": SEVERITY["o'rta"].label,
  yuqori: SEVERITY.yuqori.label,
};

/** "Past" muhimlik kulrang: yashil "yaxshi" deb o'qilardi. */
export const SEVERITY_TONE: Record<AIEvent['severity'], Tone> = {
  past: SEVERITY.past.tone,
  "o'rta": SEVERITY["o'rta"].tone,
  yuqori: SEVERITY.yuqori.tone,
};

/** Qator/kartaning chap chizig'i. */
export const SEVERITY_STRIPE: Record<AIEvent['severity'], string> = {
  past: TONE_SOLID[SEVERITY.past.tone],
  "o'rta": TONE_SOLID[SEVERITY["o'rta"].tone],
  yuqori: TONE_SOLID[SEVERITY.yuqori.tone],
};

/** Holat nomlari — src/ui/status.ts EVENT_STATUS bilan bir xil. */
export const STATUS_LABEL: Record<EventStatus, string> = {
  yangi: EVENT_STATUS.yangi.label,
  jarayonda: EVENT_STATUS.jarayonda.label,
  tasdiqlangan: EVENT_STATUS.tasdiqlangan.label,
  rad_etilgan: EVENT_STATUS.rad_etilgan.label,
  hal_qilindi: EVENT_STATUS.hal_qilindi.label,
};

export const STATUS_TONE: Record<EventStatus, Tone> = {
  yangi: EVENT_STATUS.yangi.tone,
  jarayonda: EVENT_STATUS.jarayonda.tone,
  tasdiqlangan: EVENT_STATUS.tasdiqlangan.tone,
  rad_etilgan: EVENT_STATUS.rad_etilgan.tone,
  hal_qilindi: EVENT_STATUS.hal_qilindi.tone,
};
