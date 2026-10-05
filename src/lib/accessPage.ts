import type { IntelStatus } from '../ui';
import { formatDateTime, type AccessDevice, type AccessEventItem, type DeviceStatus } from './integrationsApi';

/* Turniketlar sahifasi (/turniketlar) uchun sof yordamchilar —
 * accessPage.test.ts. So'rovlar integrationsApi.ts da. */

export type PassDirection = 'kirish' | 'chiqish';

export interface PassFilters {
  deviceId: string;
  /** '' — ikkala yo'nalish. */
  direction: '' | PassDirection;
  /** "YYYY-MM-DD". */
  date: string;
  /** Ism yoki karta raqami bo'yicha qidiruv. */
  search?: string;
  /** '' — hammasi; rad — rad etilgan o'tishlar; nomalum — egasi topilmagan karta. */
  result?: '' | 'rad' | 'nomalum';
}

export const PASS_DIRECTION_OPTIONS: { value: PassDirection; label: string }[] = [
  { value: 'kirish', label: 'Kirish' },
  { value: 'chiqish', label: 'Chiqish' },
];

/** GET /api/access/events parametrlari — bitta kun. */
export function passQuery(filters: PassFilters): Record<string, string | undefined> {
  return {
    deviceId: filters.deviceId || undefined,
    direction: filters.direction || undefined,
    from: filters.date || undefined,
    to: filters.date || undefined,
    search: filters.search?.trim() || undefined,
    granted: filters.result === 'rad' ? 'false' : undefined,
    matched: filters.result === 'nomalum' ? 'false' : undefined,
  };
}

/** Jonli oqim faqat BUGUNNI ko'rganda ma'noli: o'tgan kun o'zgarmaydi,
 * uni har 15 soniyada qayta so'rash — bekorga yuk. */
export function isLiveDay(date: string, today: string): boolean {
  return date === today;
}

/** "2026-09-24T08:10:05+05:00" -> "08:10:05". Server vaqtni institut
 * mintaqasida beradi — brauzer mintaqasiga o'girilmaydi. */
export function passTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const match = /T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso);
  if (!match) return iso;
  return `${match[1]}:${match[2]}:${match[3] ?? '00'}`;
}

/** Shaxs ustuni: tanilgan bo'lsa ismi, bo'lmasa karta/xodim raqami. */
export function passPerson(event: Pick<AccessEventItem, 'personName' | 'cardNumber' | 'employeeNo'>): {
  label: string;
  known: boolean;
} {
  if (event.personName) return { label: event.personName, known: true };
  if (event.cardNumber) return { label: `Karta ${event.cardNumber}`, known: false };
  if (event.employeeNo) return { label: `ID ${event.employeeNo}`, known: false };
  return { label: "Noma'lum", known: false };
}

export function passDirectionLabel(direction: string | null | undefined): string {
  if (direction === 'kirish') return 'Kirish';
  if (direction === 'chiqish') return 'Chiqish';
  return '—';
}

export function passResult(granted: boolean): { label: string; status: IntelStatus } {
  return granted ? { label: 'Ruxsat', status: 'ok' } : { label: 'Rad etildi', status: 'alert' };
}

export const DEVICE_LAMP: Record<DeviceStatus, IntelStatus> = {
  onlayn: 'ok',
  oflayn: 'warn',
  xato: 'alert',
  kutilmoqda: 'idle',
  ochirilgan: 'idle',
};

/** Qurilma bilan oxirgi aloqa: Hikvision'ni server o'zi so'raydi
 * (so'rov vaqti), webhook/ZKTeco esa o'zi yuboradi (oxirgi hodisa). */
export function deviceLastContact(device: Pick<AccessDevice, 'kind' | 'lastPollAt' | 'lastEventAt'>): {
  label: string;
  value: string;
} {
  if (device.kind === 'hikvision') return { label: "So'rov", value: formatDateTime(device.lastPollAt) };
  return { label: 'Hodisa', value: formatDateTime(device.lastEventAt) };
}

/** Qurilmalar ro'yxati: avval muammolilari (xato, oflayn), keyin nomi. */
export function sortDevices(devices: readonly AccessDevice[]): AccessDevice[] {
  const rank: Record<DeviceStatus, number> = { xato: 0, oflayn: 1, kutilmoqda: 2, onlayn: 3, ochirilgan: 4 };
  return [...devices].sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name));
}

/** Sarlavha yonidagi qisqa holat: "3/4 onlayn". O'chirilganlar hisobga
 * kirmaydi — ular ataylab to'xtatilgan. */
export function onlineSummary(devices: readonly Pick<AccessDevice, 'status'>[]): string {
  const active = devices.filter((d) => d.status !== 'ochirilgan');
  const online = active.filter((d) => d.status === 'onlayn').length;
  return `${online}/${active.length} onlayn`;
}
