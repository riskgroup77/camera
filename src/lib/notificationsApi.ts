import { api } from './apiClient';
import type { EventSeverity } from '../types';

/* Bildirishnomalar (Telegram + SMS) — backend: app/routers/notifications.py.
 * Sof yordamchilar (telefon formati, qabul qiluvchini tekshirish) server
 * qoidasi bilan bir xil: app/services/notifications/sms.py normalize_phone,
 * app/schemas/notifications.py clean_recipients. */

export type NotificationChannel = 'telegram' | 'sms';
export type NotificationKind =
  | 'event'
  | 'event_overdue'
  | 'camera_offline'
  | 'camera_online'
  | 'access_denied'
  | 'system'
  | 'teacher_absent';
export type NotificationLogStatus = 'yuborildi' | 'xato' | 'otkazildi';

export interface NotificationRule {
  id: string;
  name: string;
  enabled: boolean;
  channel: NotificationChannel;
  recipients: string[];
  kinds: NotificationKind[];
  moduleCodes: number[] | null;
  buildingIds: string[] | null;
  minSeverity: EventSeverity | null;
  createdAt: string;
}

export type NotificationRuleInput = Omit<NotificationRule, 'id' | 'createdAt'>;

export interface NotificationLogEntry {
  id: string;
  createdAt: string;
  channel: NotificationChannel;
  recipient: string;
  /** Qoida turlari + ota-ona xabarlari ('parent_arrival', 'parent_absence'). */
  kind: string;
  status: NotificationLogStatus;
  text: string;
  error: string | null;
  refId: string | null;
}

export interface NotificationLogPage {
  items: NotificationLogEntry[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface NotificationStatus {
  telegramConfigured: boolean;
  telegramBotUsername: string | null;
  telegramPollingEnabled: boolean;
  smsProvider: string;
  smsConfigured: boolean;
  smsSender: string | null;
  parentArrivalEnabled: boolean;
  parentAbsenceEnabled: boolean;
  orgName: string;
}

export interface MyNotifications {
  telegramLinked: boolean;
  telegramBotConfigured: boolean;
  phone: string | null;
}

export interface TelegramLink {
  code: string;
  deepLink: string;
  botUsername: string;
}

export interface NotificationTestResult {
  ok: boolean;
  error: string | null;
}

export interface NotificationLogFilters {
  page: number;
  pageSize: number;
  status?: NotificationLogStatus | '';
  channel?: NotificationChannel | '';
  kind?: string;
  search?: string;
}

// ---------------------------------------------------------------------------
// Yorliqlar
// ---------------------------------------------------------------------------

export const KIND_OPTIONS: { value: NotificationKind; label: string; hint: string }[] = [
  { value: 'event', label: 'AI hodisa', hint: 'Yangi signal (sinov rejimidagilar yuborilmaydi)' },
  { value: 'event_overdue', label: "Muddati o'tgan hodisa", hint: 'Hal qilish muddati (SLA) buzildi' },
  { value: 'camera_offline', label: "Kamera o'chdi", hint: 'Kamera javob bermay qoldi' },
  { value: 'camera_online', label: 'Kamera tiklandi', hint: "O'chgan kamera qayta ishladi" },
  { value: 'access_denied', label: 'Turniket rad etdi', hint: 'Kirish nazoratida rad etilgan urinish' },
  { value: 'system', label: 'Tizim', hint: 'Umumiy tizim xabarlari' },
  {
    value: 'teacher_absent',
    label: "O'qituvchi darsga kelmadi",
    hint: "Kamerasiz xonadagi dars: boshlanganidan 10 daqiqa o'tib ham o'qituvchini bugun hech bir kamera ko'rmagan",
  },
];

const EXTRA_KIND_LABELS: Record<string, string> = {
  parent_arrival: 'Ota-ona: keldi',
  parent_absence: 'Ota-ona: kelmadi',
};

export function kindLabel(kind: string): string {
  return KIND_OPTIONS.find((k) => k.value === kind)?.label ?? EXTRA_KIND_LABELS[kind] ?? kind;
}

export const CHANNEL_LABELS: Record<NotificationChannel, string> = {
  telegram: 'Telegram',
  sms: 'SMS',
};

export const STATUS_LABELS: Record<NotificationLogStatus, string> = {
  yuborildi: 'Yuborildi',
  xato: 'Xato',
  otkazildi: "O'tkazib yuborildi",
};

export const SEVERITY_OPTIONS: { value: EventSeverity; label: string }[] = [
  { value: 'past', label: 'Past va yuqori (hammasi)' },
  { value: "o'rta", label: "O'rta va yuqori" },
  { value: 'yuqori', label: 'Faqat yuqori' },
];

// ---------------------------------------------------------------------------
// Sof yordamchilar
// ---------------------------------------------------------------------------

/** O'zbekiston raqami -> '+998XXXXXXXXX'. Yaroqsiz bo'lsa null.
 *  '+998 90 123-45-67', '998901234567', '90 123 45 67', '8 90 123 45 67'. */
export function normalizeUzPhone(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let digits = raw.replace(/\D/g, '');
  if (digits.length === 9) digits = `998${digits}`;
  else if (digits.length === 10 && digits.startsWith('8')) digits = `998${digits.slice(1)}`;
  // Operator/hudud kodi ham tekshiriladi (backend sms.py bilan bir xil):
  // aks holda Telegram ID (123456789) yaroqli telefon deb qabul qilinardi.
  if (!/^998(20|33|50|55|6[1-9]|7[0-9]|88|9[0-9])\d{7}$/.test(digits)) return null;
  return `+${digits}`;
}

/** Ko'rsatish uchun: '+998901234567' -> '+998 90 123 45 67'. */
export function formatUzPhone(phone: string | null | undefined): string {
  const normalized = normalizeUzPhone(phone);
  if (!normalized) return phone ?? '';
  const d = normalized.slice(4);
  return `+998 ${d.slice(0, 2)} ${d.slice(2, 5)} ${d.slice(5, 7)} ${d.slice(7, 9)}`;
}

const TELEGRAM_RECIPIENT = /^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$/;

/** Qabul qiluvchini tekshiradi: [tozalangan qiymat, xato matni]. */
export function validateRecipient(channel: NotificationChannel, raw: string): [string | null, string | null] {
  const value = raw.trim();
  if (!value) return [null, null];
  if (channel === 'sms') {
    const phone = normalizeUzPhone(value);
    return phone ? [phone, null] : [null, `Telefon raqami noto'g'ri: ${value} (+998XXXXXXXXX)`];
  }
  return TELEGRAM_RECIPIENT.test(value)
    ? [value, null]
    : [null, `Telegram chat ID noto'g'ri: ${value} (raqam yoki @kanal)`];
}

/** Bir nechta qiymat bir yo'la yopishtirilganda: vergul, nuqta-vergul yoki
 *  yangi qator bilan ajratiladi (telefon ichidagi bo'shliqlar saqlanadi). */
export function splitRecipientInput(text: string): string[] {
  return text
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Qoida qisqa tavsifi (ro'yxat kartasi uchun). */
export function describeRuleFilters(
  rule: Pick<NotificationRule, 'moduleCodes' | 'buildingIds' | 'minSeverity'>,
  moduleName: (code: number) => string,
  buildingName: (id: string) => string,
): string[] {
  const parts: string[] = [];
  if (rule.moduleCodes?.length) parts.push(`Modullar: ${rule.moduleCodes.map(moduleName).join(', ')}`);
  if (rule.buildingIds?.length) parts.push(`Binolar: ${rule.buildingIds.map(buildingName).join(', ')}`);
  if (rule.minSeverity) {
    parts.push(`Daraja: ${SEVERITY_OPTIONS.find((s) => s.value === rule.minSeverity)?.label ?? rule.minSeverity}`);
  }
  return parts;
}

/** Server vaqtni Toshkent vaqtida ISO ko'rinishda beradi
 *  ('2026-09-19T14:05:07+05:00') — brauzer mintaqasiga o'girmasdan,
 *  shundayligicha '19.09.2026 14:05:07' qilib ko'rsatamiz. */
export function formatLogTime(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}:${m[6]}` : iso;
}

export function logQuery(filters: NotificationLogFilters): string {
  const params = new URLSearchParams({ page: String(filters.page), pageSize: String(filters.pageSize) });
  if (filters.status) params.set('status', filters.status);
  if (filters.channel) params.set('channel', filters.channel);
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.search?.trim()) params.set('search', filters.search.trim());
  return params.toString();
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const notificationsApi = {
  status: (token?: string | null) => api.get<NotificationStatus>('/api/notifications/status', token),
  rules: (token?: string | null) => api.get<NotificationRule[]>('/api/notifications/rules', token),
  createRule: (body: NotificationRuleInput, token?: string | null) =>
    api.post<NotificationRule>('/api/notifications/rules', body, token),
  updateRule: (id: string, body: Partial<NotificationRuleInput>, token?: string | null) =>
    api.patch<NotificationRule>(`/api/notifications/rules/${id}`, body, token),
  deleteRule: (id: string, token?: string | null) => api.del(`/api/notifications/rules/${id}`, token),
  log: (filters: NotificationLogFilters, token?: string | null, signal?: AbortSignal) =>
    api.get<NotificationLogPage>(`/api/notifications/log?${logQuery(filters)}`, token, { signal }),
  sendTest: (body: { channel: NotificationChannel; recipient: string; text?: string | null }, token?: string | null) =>
    api.post<NotificationTestResult>('/api/notifications/test', body, token),
  me: (token?: string | null) => api.get<MyNotifications>('/api/notifications/me', token),
  linkMyTelegram: (token?: string | null) => api.post<TelegramLink>('/api/notifications/me/telegram-link', {}, token),
  unlinkMyTelegram: (token?: string | null) => api.del('/api/notifications/me/telegram', token),
  parentTelegramLink: (personId: string, token?: string | null) =>
    api.post<TelegramLink>(`/api/students-staff/${personId}/parent-telegram-link`, {}, token),
  unlinkParentTelegram: (personId: string, token?: string | null) =>
    api.del(`/api/students-staff/${personId}/parent-telegram`, token),
};
