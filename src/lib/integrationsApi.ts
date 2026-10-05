import { api, buildQuery, type CallOptions, type Page } from './apiClient';
import { config } from './config';
import { ipAddress } from './validation';
import type { Tone } from '../ui/tones';

/* ── Turlar (camera-api/app/schemas/integrations.py bilan mos) ── */

export type SyncRunStatus = 'ishlamoqda' | 'muvaffaqiyatli' | 'xato';

export interface EntityStats {
  fetched: number;
  created: number;
  updated: number;
  unchanged: number;
  deactivated: number;
  skipped: number;
  errors: number;
}

export interface SyncProgress {
  stage: string;
  done: number;
  total: number;
}

export interface SyncStats {
  faculties?: EntityStats;
  departments?: EntityStats;
  groups?: EntityStats;
  students?: EntityStats;
  employees?: EntityStats;
  /** HEMIS dars jadvali (deactivated — HEMIS'dan olib tashlangan kelajakdagi darslar). */
  schedule?: EntityStats;
  progress?: SyncProgress;
  messages?: string[];
}

export interface SyncRun {
  id: string;
  source: string;
  status: SyncRunStatus;
  startedAt: string | null;
  finishedAt: string | null;
  durationSeconds: number | null;
  triggeredBy: string;
  stats: SyncStats | null;
  error: string | null;
}

export interface HemisStatus {
  configured: boolean;
  baseUrl: string | null;
  syncIntervalHours: number;
  deactivateMissing: boolean;
  pageSize: number;
  running: SyncRun | null;
  lastRun: SyncRun | null;
  lastSuccessAt: string | null;
}

export interface HemisTestResult {
  ok: boolean;
  error: string | null;
  entities: Record<string, { ok: boolean; total: number | null; error: string | null }>;
}

export type DeviceKind = 'hikvision' | 'zkteco' | 'webhook';
export type DeviceDirection = 'kirish' | 'chiqish' | 'ikkalasi';
export type DeviceStatus = 'onlayn' | 'oflayn' | 'xato' | 'kutilmoqda' | 'ochirilgan';

export interface AccessDevice {
  id: string;
  name: string;
  kind: DeviceKind;
  ip: string | null;
  port: number | null;
  username: string | null;
  hasPassword: boolean;
  hasApiKey: boolean;
  direction: DeviceDirection;
  buildingId: string | null;
  buildingName: string | null;
  marksAttendance: boolean;
  enabled: boolean;
  status: DeviceStatus;
  lastEventAt: string | null;
  lastPollAt: string | null;
  lastError: string | null;
  webhookPath: string | null;
  createdAt: string | null;
}

export interface AccessDeviceCreated extends AccessDevice {
  apiKey: string | null;
}

export interface DeviceTestResult {
  ok: boolean;
  message: string;
  info: Record<string, string | null> | null;
}

export interface AccessEventItem {
  id: string;
  deviceId: string | null;
  deviceName: string | null;
  occurredAt: string;
  cardNumber: string | null;
  employeeNo: string | null;
  personId: string | null;
  personName: string | null;
  personType: string | null;
  personUnit: string | null;
  direction: string | null;
  granted: boolean;
}

export interface UnmatchedCredential {
  cardNumber: string | null;
  employeeNo: string | null;
  count: number;
  deniedCount: number;
  firstSeen: string;
  lastSeen: string;
  lastDeviceName: string | null;
}

export interface DeviceForm {
  name: string;
  kind: DeviceKind;
  ip: string;
  port: string;
  username: string;
  password: string;
  direction: DeviceDirection;
  buildingId: string;
  marksAttendance: boolean;
  enabled: boolean;
}

/* ── So'rovlar ── */

export const integrationsApi = {
  hemisStatus: (token: string | null) => api.get<HemisStatus>('/api/integrations/hemis/status', token),
  hemisTest: (token: string | null) => api.post<HemisTestResult>('/api/integrations/hemis/test', {}, token),
  hemisSync: (token: string | null) => api.post<{ runId: string }>('/api/integrations/hemis/sync', {}, token),
  run: (id: string, token: string | null) => api.get<SyncRun>(`/api/integrations/runs/${id}`, token),
  runs: (page: number, token: string | null) =>
    api.get<Page<SyncRun>>(`/api/integrations/runs${buildQuery({ source: 'hemis', page, pageSize: 10 })}`, token),

  devices: (token: string | null, opts?: CallOptions) => api.get<AccessDevice[]>('/api/access/devices', token, opts),
  createDevice: (body: Record<string, unknown>, token: string | null) =>
    api.post<AccessDeviceCreated>('/api/access/devices', body, token),
  updateDevice: (id: string, body: Record<string, unknown>, token: string | null) =>
    api.patch<AccessDevice>(`/api/access/devices/${id}`, body, token),
  deleteDevice: (id: string, token: string | null) => api.del(`/api/access/devices/${id}`, token),
  rotateKey: (id: string, token: string | null) =>
    api.post<{ apiKey: string; webhookPath: string }>(`/api/access/devices/${id}/rotate-key`, {}, token),
  testDevice: (id: string, token: string | null) =>
    api.post<DeviceTestResult>(`/api/access/devices/${id}/test`, {}, token),
  unmatched: (days: number, token: string | null) =>
    api.get<UnmatchedCredential[]>(`/api/access/unmatched${buildQuery({ days })}`, token),
  summary: (date: string, deviceId: string | undefined, token: string | null, opts?: CallOptions) =>
    api.get<AccessSummary>(`/api/access/summary${buildQuery({ date, deviceId })}`, token, opts),
};

/** Bir kunlik o'tishlar sanog'i (GET /api/access/summary). */
export interface AccessSummary {
  date: string;
  total: number;
  entries: number;
  exits: number;
  denied: number;
  unmatched: number;
  people: number;
}

/* ── Sof yordamchilar (integrationsApi.test.ts) ── */

/** "2026-09-19T08:10:05+05:00" -> "19.09.2026 08:10". Server vaqtni
 *  institut mintaqasida beradi — brauzer mintaqasiga o'girilmaydi. */
export function formatDateTime(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso);
  if (!match) return iso;
  const [, y, m, d, hh, mm, ss] = match;
  return `${d}.${m}.${y} ${hh}:${mm}${withSeconds && ss ? `:${ss}` : ''}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest ? `${minutes} daq ${rest} s` : `${minutes} daq`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours} soat ${restMinutes} daq` : `${hours} soat`;
}

export const RUN_STATUS_META: Record<SyncRunStatus, { label: string; tone: Tone }> = {
  ishlamoqda: { label: 'Ishlamoqda', tone: 'info' },
  muvaffaqiyatli: { label: 'Muvaffaqiyatli', tone: 'success' },
  xato: { label: 'Xato', tone: 'danger' },
};

export const DEVICE_STATUS_META: Record<DeviceStatus, { label: string; tone: Tone }> = {
  onlayn: { label: 'Onlayn', tone: 'success' },
  oflayn: { label: 'Oflayn', tone: 'warning' },
  xato: { label: 'Xato', tone: 'danger' },
  kutilmoqda: { label: 'Kutilmoqda', tone: 'neutral' },
  ochirilgan: { label: "O'chirilgan", tone: 'neutral' },
};

export const KIND_LABELS: Record<DeviceKind, string> = {
  hikvision: 'Hikvision (ISAPI)',
  zkteco: 'ZKTeco',
  webhook: 'Webhook',
};

export const DIRECTION_LABELS: Record<DeviceDirection, string> = {
  kirish: 'Kirish',
  chiqish: 'Chiqish',
  ikkalasi: 'Ikkalasi',
};

export const ENTITY_ORDER: { key: keyof Omit<SyncStats, 'progress' | 'messages'>; label: string }[] = [
  { key: 'students', label: 'Talabalar' },
  { key: 'employees', label: 'Xodimlar' },
  { key: 'groups', label: 'Guruhlar' },
  { key: 'faculties', label: 'Fakultetlar' },
  { key: 'departments', label: 'Kafedralar' },
  { key: 'schedule', label: 'Dars jadvali' },
];

export interface StatsRow extends EntityStats {
  key: string;
  label: string;
}

/** Jadval uchun: faqat nimadir sodir bo'lgan (yuklangan yoki o'zgargan) bo'limlar. */
export function statsRows(stats: SyncStats | null | undefined): StatsRow[] {
  if (!stats) return [];
  const rows: StatsRow[] = [];
  for (const { key, label } of ENTITY_ORDER) {
    const entity = stats[key];
    if (!entity) continue;
    const touched = Object.values(entity).some((value) => typeof value === 'number' && value > 0);
    if (touched) rows.push({ key, label, ...entity });
  }
  return rows;
}

/** Qisqa xulosa: "Talabalar: +12, ~40, −3". */
export function statsSummary(stats: SyncStats | null | undefined): string {
  const parts = statsRows(stats)
    .filter((row) => row.created || row.updated || row.deactivated || row.errors)
    .map((row) => {
      const bits = [
        row.created ? `+${row.created}` : null,
        row.updated ? `~${row.updated}` : null,
        row.deactivated ? `−${row.deactivated}` : null,
        row.errors ? `${row.errors} xato` : null,
      ].filter(Boolean);
      return `${row.label}: ${bits.join(', ')}`;
    });
  return parts.length ? parts.join(' · ') : "O'zgarish yo'q";
}

/** Jarayon foizi; bosqich hajmi noma'lum bo'lsa null. */
export function progressPercent(progress: SyncProgress | null | undefined): number | null {
  if (!progress || !progress.total || progress.total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((progress.done / progress.total) * 100)));
}

/** Webhook to'liq manzili: API boshqa domenda bo'lsa uning manzili,
 *  bo'lmasa sahifaning o'zi (nginx /api ni proksilaydi). */
export function webhookUrl(path: string, apiBase: string = config.apiBaseUrl, origin?: string): string {
  const base = (apiBase || origin || (typeof window !== 'undefined' ? window.location.origin : '')).replace(/\/+$/, '');
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

export const EMPTY_DEVICE_FORM: DeviceForm = {
  name: '',
  kind: 'hikvision',
  ip: '',
  port: '80',
  username: '',
  password: '',
  direction: 'kirish',
  buildingId: '',
  marksAttendance: true,
  enabled: true,
};

export function deviceToForm(device: AccessDevice): DeviceForm {
  return {
    name: device.name,
    kind: device.kind,
    ip: device.ip ?? '',
    port: device.port ? String(device.port) : '',
    username: device.username ?? '',
    password: '',
    direction: device.direction,
    buildingId: device.buildingId ?? '',
    marksAttendance: device.marksAttendance,
    enabled: device.enabled,
  };
}

/** Forma tekshiruvi — xato matnlari maydon bo'yicha. */
export function validateDeviceForm(form: DeviceForm, isEdit: boolean): Partial<Record<keyof DeviceForm, string>> {
  const errors: Partial<Record<keyof DeviceForm, string>> = {};
  if (!form.name.trim()) errors.name = 'Nomini kiriting';
  if (form.port.trim()) {
    const port = Number(form.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) errors.port = 'Port 1–65535 oralig\'ida';
  }
  if (form.kind === 'hikvision') {
    // Manzil shakli tekshiriladi: ilgari "kamera-1" kabi matn ham qabul
    // qilinardi (server ham uni oddiy satr deb saqlaydi), keyin qurilma
    // abadiy "xato" holatida turib, sababi tushunarsiz bo'lardi.
    if (!form.ip.trim()) errors.ip = 'IP manzilni kiriting';
    else errors.ip = ipAddress(form.ip);
    if (!errors.ip) delete errors.ip;
    if (!form.username.trim()) errors.username = 'Loginni kiriting';
    if (!isEdit && !form.password) errors.password = 'Parolni kiriting';
  }
  return errors;
}

/** API tanasi. Tahrirlashda bo'sh parol yuborilmaydi (o'zgarmaydi);
 *  qurilma turi faqat yaratishda. */
export function buildDevicePayload(form: DeviceForm, isEdit: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: form.name.trim(),
    ip: form.ip.trim() || null,
    port: form.port.trim() ? Number(form.port) : null,
    username: form.username.trim() || null,
    direction: form.direction,
    buildingId: form.buildingId || null,
    marksAttendance: form.marksAttendance,
    enabled: form.enabled,
  };
  if (!isEdit) body.kind = form.kind;
  if (form.password) body.password = form.password;
  return body;
}

/** Reestr (odamlar) sahifasida shu raqam/ism bo'yicha qidirish havolasi. */
export function peopleSearchLink(value: string): string {
  return `/reestr${buildQuery({ search: value })}`;
}
