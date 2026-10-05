import { api, buildQuery, type CallOptions } from './apiClient';
import type { Tone } from '../ui/tones';

/* ── Turlar (camera-api/app/schemas/video_analysis.py bilan mos) ── */

export type RunStatus = 'navbatda' | 'ishlamoqda' | 'agregatsiya' | 'tugadi' | 'xato' | 'bekor';

export interface AnalysisRun {
  id: string;
  day: string;
  status: RunStatus;
  windowStart: string;
  windowEnd: string;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  jobsTotal: number;
  jobsDone: number;
  jobsFailed: number;
  jobsNoVideo: number;
  framesPlanned: number;
  framesAnalyzed: number;
  facesDetected: number;
  observations: number;
  progress: number;
  stats: Record<string, number | string> | null;
  error: string | null;
  triggeredBy: string;
}

export interface RunDetail extends AnalysisRun {
  jobs: { kind: string; status: string; count: number; frames: number }[];
  errors: { cameraName: string | null; kind: string; status: string; error: string | null; startAt: string }[];
}

export interface AnalysisStatus {
  mode: 'kunlik' | 'realtime';
  startTime: string;
  dayStart: string;
  nextRunAt: string | null;
  nvrCount: number;
  mappedCameras: number;
  activeCameras: number;
  current: AnalysisRun | null;
  last: AnalysisRun | null;
}

export type CoatStatus = 'kiygan' | 'kiymagan' | 'aniqlanmadi' | 'talab_yoq';
export type EarlyLeave = 'erta_ketdi' | 'vaqtida' | 'aniqlanmadi' | 'tegishli_emas';

export interface DailyCriteriaRow {
  personId: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  groupOrPosition: string;
  day: string;
  attendanceStatus: string | null;
  arrivedAt: string | null;
  leftAt: string | null;
  lateMinutes: number | null;
  earlyLeave: EarlyLeave | null;
  sightings: number;
  camerasSeen: number;
  lessonsTotal: number | null;
  lessonsAttended: number | null;
  lessonsLate: number | null;
  lessonsLeftEarly: number | null;
  lessonsUnmeasured: number | null;
  attentionScore: number | null;
  coatStatus: CoatStatus | null;
  coatSamples: number;
  coatWhiteSamples: number;
  smokingEvents: number;
  teacherLessons: number | null;
  teacherOnTime: number | null;
  teacherLate: number | null;
  teacherAbsent: number | null;
  teacherActivity: number | null;
  /** Aniqlangan holatlar soni (ro'yxatda) va o'zlari (odam tarixida, video havolasi bilan). */
  evidenceCount: number;
  evidence: Evidence[];
}

/** Bitta aniqlangan holat: kriteriya kodi, sababi, payti va 2 daqiqalik video dalil. */
export interface Evidence {
  code: number;
  reason: string;
  at: string;
  cameraName: string | null;
  clipUrl: string | null;
  clipError: string | null;
}

export const CRITERIA_NAMES: Record<number, string> = {
  6: 'Xodim davomati',
  7: 'Talaba davomati',
  8: 'Darsga kechikish',
  9: 'Erta ketish',
  10: 'Oq xalat',
  15: 'Chekish',
  19: 'Darsga diqqat',
  21: "O'qituvchi faolligi",
  22: "O'qituvchining darsga kelishi",
};

export interface CriteriaSummary {
  day: string;
  people: number;
  present: number;
  late: number;
  absent: number;
  earlyLeave: number;
  lessonsLate: number;
  lessonsLeftEarly: number;
  attentionAvg: number | null;
  coatYes: number;
  coatNo: number;
  coatUnknown: number;
  smoking: number;
  teacherOnTime: number;
  teacherLate: number;
  teacherAbsent: number;
  teacherActivityAvg: number | null;
  run: AnalysisRun | null;
}

export interface Nvr {
  id: string;
  name: string;
  kind: 'hikvision' | 'fayl';
  ip: string | null;
  httpPort: number;
  rtspPort: number;
  username: string | null;
  hasPassword: boolean;
  stream: 'main' | 'sub';
  fetchMode: 'download' | 'rtsp';
  maxStreams: number;
  localTime: boolean;
  rtspPathTemplate: string;
  basePath: string | null;
  enabled: boolean;
  lastCheckAt: string | null;
  lastError: string | null;
  channelCount: number | null;
  cameras: number;
}

export interface NvrInput {
  name: string;
  kind: 'hikvision' | 'fayl';
  ip?: string | null;
  httpPort?: number;
  rtspPort?: number;
  username?: string | null;
  /** Bo'sh — o'zgartirilmaydi (tahrirlashda). */
  password?: string | null;
  stream?: 'main' | 'sub';
  fetchMode?: 'download' | 'rtsp';
  maxStreams?: number;
  localTime?: boolean;
  basePath?: string | null;
  enabled?: boolean;
}

export interface NvrChannel {
  channel: number;
  name: string;
  ip: string | null;
  online: boolean | null;
  cameraId: string | null;
  cameraName: string | null;
}

/** Natijalar jadvalidagi tezkor filtrlar (backend FILTERS bilan mos). */
export const RESULT_FILTERS = [
  { value: 'kech', label: 'Kech kelganlar' },
  { value: 'kelmadi', label: 'Kelmaganlar' },
  { value: 'erta_ketdi', label: 'Ishdan erta ketganlar' },
  { value: 'darsga_kech', label: 'Darsga kechikkanlar' },
  { value: 'darsdan_erta', label: 'Darsdan erta chiqqanlar' },
  { value: 'diqqat_past', label: 'Diqqati past (<60)' },
  { value: 'xalatsiz', label: 'Oq xalatsiz' },
  { value: 'chekish', label: 'Chekish holati' },
  { value: 'oqituvchi_kech', label: "O'qituvchi kechikkan/kelmagan" },
  { value: 'holatli', label: 'Holati (dalili) borlar' },
] as const;

export type ResultFilter = (typeof RESULT_FILTERS)[number]['value'];

export const RUN_STATUS_META: Record<RunStatus, { label: string; tone: Tone }> = {
  navbatda: { label: 'Navbatda', tone: 'neutral' },
  ishlamoqda: { label: 'Tahlil qilinmoqda', tone: 'info' },
  agregatsiya: { label: 'Natijalar hisoblanmoqda', tone: 'info' },
  tugadi: { label: 'Tugadi', tone: 'success' },
  xato: { label: 'Xato', tone: 'danger' },
  bekor: { label: 'Bekor qilindi', tone: 'warning' },
};

export const COAT_META: Record<CoatStatus, { label: string; tone: Tone }> = {
  kiygan: { label: 'Kiygan', tone: 'success' },
  kiymagan: { label: 'Kiymagan', tone: 'danger' },
  aniqlanmadi: { label: 'Aniqlanmadi', tone: 'neutral' },
  talab_yoq: { label: 'Talab yo‘q', tone: 'neutral' },
};

export const EARLY_LEAVE_META: Record<EarlyLeave, { label: string; tone: Tone }> = {
  erta_ketdi: { label: 'Erta ketdi', tone: 'danger' },
  vaqtida: { label: 'Vaqtida', tone: 'success' },
  aniqlanmadi: { label: 'Aniqlanmadi', tone: 'neutral' },
  tegishli_emas: { label: '—', tone: 'neutral' },
};

export const JOB_KIND_LABELS: Record<string, string> = {
  kirish: 'Kirish/chiqish',
  dars: 'Darslar',
  umumiy: 'Boshqa kameralar',
  chekish: 'Chekish (tashqi)',
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  navbatda: 'navbatda',
  ishlamoqda: 'ishlamoqda',
  tugadi: 'tugadi',
  xato: 'xato',
  yozuv_yoq: 'yozuv yo‘q',
  bekor: 'bekor',
};

export function isRunActive(run: AnalysisRun | null | undefined): boolean {
  return Boolean(run && (run.status === 'navbatda' || run.status === 'ishlamoqda' || run.status === 'agregatsiya'));
}

/** "08:12" — ISO vaqt belgisining soat:daqiqa qismi (server institut soatida yuboradi). */
export function clockOf(iso: string | null | undefined): string {
  if (!iso) return '—';
  const match = /T(\d{2}:\d{2})/.exec(iso);
  return match ? match[1] : '—';
}

/** Darslar katagi: "2/3", kechikish va erta chiqish bilan. */
export function lessonsSummary(row: Pick<DailyCriteriaRow, 'lessonsTotal' | 'lessonsAttended' | 'lessonsLate' | 'lessonsLeftEarly' | 'lessonsUnmeasured'>): string {
  if (!row.lessonsTotal) return '—';
  const measured = row.lessonsTotal - (row.lessonsUnmeasured ?? 0);
  if (measured <= 0) return 'o‘lchanmadi';
  const parts = [`${row.lessonsAttended ?? 0}/${measured}`];
  if (row.lessonsLate) parts.push(`${row.lessonsLate} kech`);
  if (row.lessonsLeftEarly) parts.push(`${row.lessonsLeftEarly} erta`);
  return parts.join(' · ');
}

/** O'qituvchi katagi: vaqtida/kech/kelmadi. */
export function teacherSummary(row: Pick<DailyCriteriaRow, 'teacherLessons' | 'teacherOnTime' | 'teacherLate' | 'teacherAbsent'>): string {
  if (!row.teacherLessons) return '—';
  const parts = [`${row.teacherOnTime ?? 0}/${row.teacherLessons} vaqtida`];
  if (row.teacherLate) parts.push(`${row.teacherLate} kech`);
  if (row.teacherAbsent) parts.push(`${row.teacherAbsent} kelmadi`);
  return parts.join(' · ');
}

/** Tahlil jarayoni matni: "34 / 120 vazifa · 12 400 kadr". */
export function runProgressText(run: AnalysisRun): string {
  const frames = run.framesAnalyzed.toLocaleString('ru-RU');
  return `${run.jobsDone + run.jobsFailed} / ${run.jobsTotal} vazifa · ${frames} kadr`;
}

/** Qolgan vaqt bahosi (daqiqa) — bajarilgan vazifalar tezligidan. */
export function etaMinutes(run: AnalysisRun, now: number = Date.now()): number | null {
  if (!run.startedAt || run.framesAnalyzed <= 0 || run.framesPlanned <= 0) return null;
  const started = Date.parse(run.startedAt);
  if (Number.isNaN(started) || now <= started) return null;
  const rate = run.framesAnalyzed / ((now - started) / 60_000);
  const remaining = Math.max(0, run.framesPlanned - run.framesAnalyzed);
  if (rate <= 0) return null;
  return Math.round(remaining / rate);
}

const BASE = '/api/video-tahlil';

export const videoAnalysisApi = {
  status: (token?: string | null, opts?: CallOptions) => api.get<AnalysisStatus>(`${BASE}/holat`, token, opts),
  runs: (token?: string | null, limit = 30) => api.get<AnalysisRun[]>(`${BASE}/ishlar${buildQuery({ limit })}`, token),
  run: (id: string, token?: string | null) => api.get<RunDetail>(`${BASE}/ishlar/${id}`, token),
  start: (day: string, token?: string | null) => api.post<AnalysisRun>(`${BASE}/ishlar`, { day }, token),
  cancel: (id: string, token?: string | null) => api.post<AnalysisRun>(`${BASE}/ishlar/${id}/bekor`, {}, token),
  summary: (day: string | undefined, token?: string | null, opts?: CallOptions) =>
    api.get<CriteriaSummary>(`${BASE}/natijalar/xulosa${buildQuery({ day })}`, token, opts),
  person: (personId: string, token?: string | null, from?: string, to?: string) =>
    api.get<DailyCriteriaRow[]>(`${BASE}/natijalar/odam/${personId}${buildQuery({ from, to })}`, token),
  exportXlsx: (day: string, type: string | undefined, token?: string | null) =>
    api.blob(`${BASE}/natijalar/export.xlsx${buildQuery({ day, type })}`, token),
  nvrs: (token?: string | null) => api.get<Nvr[]>(`${BASE}/nvr`, token),
  createNvr: (body: NvrInput, token?: string | null) => api.post<Nvr>(`${BASE}/nvr`, body, token),
  updateNvr: (id: string, body: Partial<NvrInput>, token?: string | null) => api.patch<Nvr>(`${BASE}/nvr/${id}`, body, token),
  deleteNvr: (id: string, token?: string | null) => api.del(`${BASE}/nvr/${id}`, token),
  testNvr: (id: string, token?: string | null) =>
    api.post<{ ok: boolean; message: string; model: string | null; channels: number | null }>(`${BASE}/nvr/${id}/tekshirish`, {}, token),
  channels: (id: string, token?: string | null) => api.get<NvrChannel[]>(`${BASE}/nvr/${id}/kanallar`, token),
  autoMap: (id: string, token?: string | null) =>
    api.post<{ mapped: number; unmatchedChannels: number[]; unmappedCameras: number }>(`${BASE}/nvr/${id}/avto-boglash`, {}, token),
};

export const RESULTS_PATH = `${BASE}/natijalar`;
