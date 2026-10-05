import type { AIEvent, EventStatus } from '../../types';

/** Ko'rib chiqish navbati — qaror kutayotgan hodisalar. */
export const QUEUE_STATUSES = 'yangi,jarayonda';

/** Tezkor filtrlar: menga tayinlangan, muddati o'tgan, hech kimga tayinlanmagan. */
export type Quick = '' | 'mening' | 'muddati' | 'tayinlanmagan';

export interface EventFilters {
  /** Navbat ko'rinishi (faqat yangi/jarayonda). */
  queue: boolean;
  severity: '' | AIEvent['severity'];
  statusFilter: '' | EventStatus;
  quick: Quick;
  moduleCode: string;
  building: string;
  from: string;
  to: string;
  search: string;
}

export type EventQueryParams = Record<string, string | undefined>;

/**
 * Ro'yxat so'rovi va CSV eksporti BITTA joydan filtr yasaydi.
 *
 * Ilgari eksport o'z nusxasini tuzardi va undan `tayinlanmagan` tezkor
 * filtriga biriktirilgan holat cheklovi (`yangi,jarayonda`) TUSHIB
 * QOLGAN edi: ekranda tayinlanmagan ochiq signallar ko'rinardi, faylga
 * esa yopilganlari ham (jumladan ommaviy yopilgan ~2680 yozuv) tushardi.
 * Tekshiruvga beriladigan faylda bu jiddiy farq — endi bitta funksiya.
 */
export function eventQueryParams(f: EventFilters): EventQueryParams {
  return {
    severity: f.severity || undefined,
    status: f.queue ? QUEUE_STATUSES : f.statusFilter || (f.quick === 'tayinlanmagan' ? QUEUE_STATUSES : undefined),
    assignedTo: f.quick === 'mening' ? 'me' : f.quick === 'tayinlanmagan' ? 'none' : undefined,
    overdue: f.quick === 'muddati' ? 'true' : undefined,
    moduleCodes: f.moduleCode || undefined,
    building: f.building || undefined,
    from: f.from || undefined,
    to: f.to || undefined,
    search: f.search.trim() || undefined,
  };
}
