import { api, buildQuery } from './apiClient';
import { splitRecipientInput, validateRecipient } from './notificationsApi';
import { LATE_RAG, RATE_RAG, rag, type Rag, type RagThresholds } from '../ui/rag';

/* Rahbariyat KPI paneli va avtomatik hisobotlar.
 * Backend: app/routers/kpi.py (GET /api/kpi), app/routers/hisobot_jadval.py. */

export interface KpiAttendance {
  rate: number | null;
  prevRate: number | null;
  latePct: number | null;
  prevLatePct: number | null;
  present: number;
  late: number;
  absent: number;
  daysCovered: number;
}

export interface KpiModuleRow {
  code: number;
  name: string;
  events: number;
  reviewed: number;
  rejected: number;
  confirmed: number;
  open: number;
  falsePct: number | null;
  reviewMinutes: number | null;
  resolveMinutes: number | null;
}

export interface KpiReport {
  period: { from: string; to: string; days: number };
  attendance: {
    students: KpiAttendance;
    staff: KpiAttendance;
    previous: { from: string; to: string };
  };
  recognition: {
    studentsCoverage: number | null;
    staffCoverage: number | null;
    studentsEnrolled: number;
    studentsTotal: number;
    staffEnrolled: number;
    staffTotal: number;
    recognisedDailyPct: number | null;
    unknownPending: number;
  };
  security: Omit<KpiModuleRow, 'code' | 'name'> & { modules: KpiModuleRow[] };
  infrastructure: {
    camerasTotal: number;
    camerasActive: number;
    camerasOnline: number;
    videoFlowing: number;
    onlinePct: number | null;
  };
}

export const kpiPath = (from: string, to: string) => `/api/kpi${buildQuery({ dan: from, gacha: to })}`;

// ---------------------------------------------------------------------------
// Svetofor chegaralari (kam bo'lgani yaxshi — teskari: ok < warn)
// ---------------------------------------------------------------------------

/** Yolg'on signal ulushi, %. */
export const FALSE_RAG: RagThresholds = { ok: 20, warn: 40 };
/** Birinchi ko'rib chiqishgacha, daqiqa. */
export const REVIEW_RAG: RagThresholds = { ok: 15, warn: 60 };

// ---------------------------------------------------------------------------
// Sof yordamchilar
// ---------------------------------------------------------------------------

export type TrendDir = 'up' | 'down' | 'flat';

export interface Trend {
  dir: TrendDir;
  delta: number;
  /** O'zgarish yaxshi tomonga (true), yomonga (false), o'zgarmagan (null). */
  good: boolean | null;
}

/** Oldingi davrga nisbatan o'zgarish. Qiymatlardan biri yo'q — null. */
export function trendOf(cur: number | null, prev: number | null, higherIsBetter = true): Trend | null {
  if (cur === null || prev === null || !Number.isFinite(cur) || !Number.isFinite(prev)) return null;
  const delta = Math.round((cur - prev) * 10) / 10;
  if (delta === 0) return { dir: 'flat', delta: 0, good: null };
  const dir: TrendDir = delta > 0 ? 'up' : 'down';
  return { dir, delta, good: dir === 'up' ? higherIsBetter : !higherIsBetter };
}

/** Daqiqa -> "12 daq" / "2.5 soat" / "—". */
export function formatMinutes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  if (value < 60) return `${Math.round(value)} daq`;
  return `${(Math.round((value / 60) * 10) / 10).toString()} soat`;
}

export function formatPct(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : `${Math.round(value * 10) / 10}%`;
}

export interface KpiTile {
  key: string;
  label: string;
  value: string;
  rag: Rag;
  trend: Trend | null;
  /** Qisqa izoh (sonlar). */
  hint?: string;
}

/** Guruhlangan plitkalar: har guruh bitta savolga javob. */
export interface KpiGroup {
  title: string;
  tiles: KpiTile[];
}

export function kpiGroups(data: KpiReport): KpiGroup[] {
  const { staff, students } = data.attendance;
  const rec = data.recognition;
  const sec = data.security;
  const inf = data.infrastructure;
  return [
    {
      title: 'Davomat',
      tiles: [
        { key: 'staffRate', label: 'Xodimlar', value: formatPct(staff.rate), rag: rag(staff.rate, RATE_RAG),
          trend: trendOf(staff.rate, staff.prevRate) },
        { key: 'studentsRate', label: 'Talabalar', value: formatPct(students.rate), rag: rag(students.rate, RATE_RAG),
          trend: trendOf(students.rate, students.prevRate) },
        { key: 'staffLate', label: 'Kechikish, xodim', value: formatPct(staff.latePct), rag: rag(staff.latePct, LATE_RAG),
          trend: trendOf(staff.latePct, staff.prevLatePct, false) },
        { key: 'studentsLate', label: 'Kechikish, talaba', value: formatPct(students.latePct),
          rag: rag(students.latePct, LATE_RAG), trend: trendOf(students.latePct, students.prevLatePct, false) },
      ],
    },
    {
      title: 'Yuzni tanish',
      tiles: [
        { key: 'staffCoverage', label: 'Yuz bazasi, xodim', value: formatPct(rec.staffCoverage),
          rag: rag(rec.staffCoverage, RATE_RAG), trend: null, hint: `${rec.staffEnrolled}/${rec.staffTotal}` },
        { key: 'studentsCoverage', label: 'Yuz bazasi, talaba', value: formatPct(rec.studentsCoverage),
          rag: rag(rec.studentsCoverage, RATE_RAG), trend: null, hint: `${rec.studentsEnrolled}/${rec.studentsTotal}` },
        { key: 'recognised', label: 'Kuniga tanilgan', value: formatPct(rec.recognisedDailyPct),
          rag: rag(rec.recognisedDailyPct, RATE_RAG), trend: null },
        { key: 'unknown', label: 'Notanish yuzlar', value: String(rec.unknownPending), rag: 'yoq', trend: null,
          hint: 'ko‘rib chiqish kutmoqda' },
      ],
    },
    {
      title: 'Xavfsizlik',
      tiles: [
        { key: 'events', label: 'Hodisalar', value: String(sec.events), rag: 'yoq', trend: null,
          hint: `${sec.open} ochiq` },
        { key: 'false', label: 'Yolg‘on signal', value: formatPct(sec.falsePct), rag: rag(sec.falsePct, FALSE_RAG),
          trend: null, hint: `${sec.rejected}/${sec.reviewed}` },
        { key: 'review', label: 'Javob vaqti', value: formatMinutes(sec.reviewMinutes),
          rag: rag(sec.reviewMinutes, REVIEW_RAG), trend: null },
        { key: 'resolve', label: 'Hal qilish', value: formatMinutes(sec.resolveMinutes), rag: 'yoq', trend: null },
      ],
    },
    {
      title: 'Kameralar',
      tiles: [
        { key: 'online', label: 'Ishlayapti', value: formatPct(inf.onlinePct), rag: rag(inf.onlinePct, RATE_RAG),
          trend: null, hint: `${inf.camerasOnline}/${inf.camerasActive}` },
        { key: 'total', label: 'Jami', value: String(inf.camerasTotal), rag: 'yoq', trend: null,
          hint: `${inf.camerasActive} faol` },
      ],
    },
  ];
}

// ---------------------------------------------------------------------------
// Avtomatik hisobotlar
// ---------------------------------------------------------------------------

export type ScheduleKind = 'kunlik' | 'haftalik' | 'oylik';
export type ScheduleReport = 'kpi' | 'davomat_xodim' | 'davomat_talaba' | 'tabel_xodim' | 'tabel_talaba' | 'jadval_davomat';

export interface ReportSchedule {
  id: string;
  name: string;
  kind: ScheduleKind;
  report: ScheduleReport;
  telegramChatIds: string[];
  enabled: boolean;
  lastSentAt: string | null;
  createdAt: string | null;
}

export type ReportScheduleInput = Pick<ReportSchedule, 'name' | 'kind' | 'report' | 'telegramChatIds' | 'enabled'>;

export interface ScheduleSendResult {
  sent: number;
  failed: number;
  errors: string[];
  periodFrom: string;
  periodTo: string;
}

export const SCHEDULE_KIND_OPTIONS: { value: ScheduleKind; label: string }[] = [
  { value: 'kunlik', label: 'Kunlik (har kuni 21:00, o‘sha kun uchun)' },
  { value: 'haftalik', label: 'Haftalik (dushanba 08:00)' },
  { value: 'oylik', label: 'Oylik (1-sana 08:00)' },
];

export const SCHEDULE_REPORT_OPTIONS: { value: ScheduleReport; label: string }[] = [
  { value: 'kpi', label: 'KPI' },
  { value: 'davomat_xodim', label: 'Xodimlar davomati' },
  { value: 'davomat_talaba', label: 'Talabalar davomati' },
  { value: 'tabel_xodim', label: 'Xodimlar tabeli' },
  { value: 'tabel_talaba', label: 'Talabalar tabeli' },
  { value: 'jadval_davomat', label: 'Jadval bo‘yicha davomat (darslar kesimida)' },
];

export function scheduleLabel(s: Pick<ReportSchedule, 'kind' | 'report'>): string {
  const report = SCHEDULE_REPORT_OPTIONS.find((o) => o.value === s.report)?.label ?? s.report;
  const kind = s.kind === 'kunlik' ? 'Kunlik' : s.kind === 'haftalik' ? 'Haftalik' : 'Oylik';
  return `${kind} · ${report}`;
}

/** Chat ID matnini ajratadi va tekshiradi (bildirishnoma qoidalari bilan bir xil). */
export function parseChatIds(text: string): { ids: string[]; error: string | null } {
  const ids: string[] = [];
  for (const part of splitRecipientInput(text)) {
    const [value, error] = validateRecipient('telegram', part);
    if (error) return { ids, error };
    if (value && !ids.includes(value)) ids.push(value);
  }
  return { ids, error: ids.length ? null : 'Kamida bitta chat ID kiriting' };
}

export const reportSchedulesApi = {
  list: (token?: string | null) => api.get<ReportSchedule[]>('/api/hisobot-jadval', token),
  create: (body: ReportScheduleInput, token?: string | null) =>
    api.post<ReportSchedule>('/api/hisobot-jadval', body, token),
  update: (id: string, body: Partial<ReportScheduleInput>, token?: string | null) =>
    api.patch<ReportSchedule>(`/api/hisobot-jadval/${id}`, body, token),
  remove: (id: string, token?: string | null) => api.del(`/api/hisobot-jadval/${id}`, token),
  sendNow: (id: string, token?: string | null) =>
    api.post<ScheduleSendResult>(`/api/hisobot-jadval/${id}/sinov`, {}, token),
};
