import { api, buildQuery, type CallOptions } from './apiClient';
import type { Rag } from '../ui/rag';
import type { Tone } from '../ui/tones';

/** Kameralar salomatligi (camera-api/app/routers/camera_health.py). */

export type CameraHealthState = 'online' | 'offline' | 'no_video';

export interface CameraHealthRow {
  id: string;
  name: string;
  building: string | null;
  floor: number | null;
  ip: string;
  status: CameraHealthState;
  lastSeenAt: string | null;
  lastFrameAt: string | null;
  offlineSince: string | null;
  uptimeDay: number;
  uptimeWeek: number;
  outagesWeek: number;
  /** null — MediaMTX javob bermadi (noma'lum). */
  liveReady: boolean | null;
  recordingReady: boolean | null;
  recordingMbps: number | null;
  aiLastAnalyzedAt: string | null;
  aiStream: string | null;
}

export interface CameraHealthSummary {
  total: number;
  online: number;
  offline: number;
  noVideo: number;
  avgUptimeDay: number | null;
  recording: number | null;
}

export interface CameraHealthDashboard {
  generatedAt: string;
  mediamtxReachable: boolean;
  recordingEnabled: boolean;
  summary: CameraHealthSummary;
  cameras: CameraHealthRow[];
}

export interface CameraOutage {
  id: string;
  startedAt: string;
  endedAt: string | null;
  durationSeconds: number;
  reason: string;
}

export interface CameraOutageList {
  cameraId: string;
  cameraName: string;
  days: number;
  items: CameraOutage[];
}

export function getCameraHealth(opts: CallOptions = {}): Promise<CameraHealthDashboard> {
  return api.get<CameraHealthDashboard>('/api/kamera-salomatligi', undefined, opts);
}

export function getCameraOutages(cameraId: string, kun = 30, opts: CallOptions = {}): Promise<CameraOutageList> {
  return api.get<CameraOutageList>(
    `/api/kamera-salomatligi/${encodeURIComponent(cameraId)}/uzilishlar${buildQuery({ kun })}`,
    undefined,
    opts,
  );
}

// ---------------------------------------------------------------------------
// Sof yordamchilar (testlanadi)
// ---------------------------------------------------------------------------

export type HealthFilter = 'hammasi' | 'oflayn' | 'tasvirsiz' | 'ai_yoq';

export const HEALTH_FILTERS: readonly { id: HealthFilter; label: string }[] = [
  { id: 'hammasi', label: 'Hammasi' },
  { id: 'oflayn', label: 'Oflayn' },
  { id: 'tasvirsiz', label: 'Tasvirsiz' },
  { id: 'ai_yoq', label: 'AI tekshirmayapti' },
];

export const STATE_META: Record<CameraHealthState, { label: string; tone: Tone; rag: Rag }> = {
  online: { label: 'Onlayn', tone: 'success', rag: 'yashil' },
  no_video: { label: 'Tasvirsiz', tone: 'warning', rag: 'sariq' },
  offline: { label: 'Oflayn', tone: 'danger', rag: 'qizil' },
};

/** Onlayn kamerani AI 15 daqiqadan beri tekshirmagan (yoki hech qachon) —
 *  video bor, lekin davomat yozilmaydi. Oflayn kamera bu ro'yxatga kirmaydi
 *  (uning sababi boshqa). Video yozuv o'chirilgan: NVR saqlaydi. */
export const AI_STALE_MS = 15 * 60_000;

export function isAiStale(row: CameraHealthRow, now: number = Date.now()): boolean {
  if (row.status !== 'online') return false;
  if (!row.aiLastAnalyzedAt) return true;
  const at = Date.parse(row.aiLastAnalyzedAt);
  return Number.isNaN(at) || now - at > AI_STALE_MS;
}

export function matchesFilter(row: CameraHealthRow, filter: HealthFilter): boolean {
  switch (filter) {
    case 'oflayn':
      return row.status === 'offline';
    case 'tasvirsiz':
      return row.status === 'no_video';
    case 'ai_yoq':
      return isAiStale(row);
    default:
      return true;
  }
}

export function filterCameras(rows: readonly CameraHealthRow[], filter: HealthFilter, query = ''): CameraHealthRow[] {
  const q = query.trim().toLowerCase();
  return rows.filter(
    (row) =>
      matchesFilter(row, filter) &&
      (!q || row.name.toLowerCase().includes(q) || row.ip.includes(q) || (row.building ?? '').toLowerCase().includes(q)),
  );
}

export function filterCounts(rows: readonly CameraHealthRow[]): Record<HealthFilter, number> {
  const out: Record<HealthFilter, number> = { hammasi: 0, oflayn: 0, tasvirsiz: 0, ai_yoq: 0 };
  for (const row of rows) {
    for (const f of HEALTH_FILTERS) if (matchesFilter(row, f.id)) out[f.id] += 1;
  }
  return out;
}

/** 99.5 -> "99,5%", 100 -> "100%", 97.123 -> "97,1%". */
export function formatUptime(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const rounded = value >= 99.95 ? 100 : Math.floor(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1).replace('.', ',')}%`;
}

/** Kamera uchun uptime chegaralari davomatnikidan qattiqroq: kuniga 1%
 *  ham ~15 daqiqa ko'rlik degani. */
export function uptimeRag(value: number | null | undefined): Rag {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'yoq';
  if (value >= 99) return 'yashil';
  if (value >= 95) return 'sariq';
  return 'qizil';
}

/** Soniyalar -> "45 s", "12 daq", "3 soat 5 daq", "2 kun 4 soat". */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return `${minutes} daq`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours} soat ${minutes % 60} daq` : `${hours} soat`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days} kun ${hours % 24} soat` : `${days} kun`;
}

export function locationLabel(row: Pick<CameraHealthRow, 'building' | 'floor'>): string {
  const parts = [row.building, row.floor !== null && row.floor !== undefined ? `${row.floor}-qavat` : null].filter(Boolean);
  return parts.length ? parts.join(' · ') : '—';
}
