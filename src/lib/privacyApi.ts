import { api, ApiError, type Page } from './apiClient';
import { calendarDateInTashkent } from './uzDate';
import { config } from './config';

/** Maxfiylik sahifasi (/sozlamalar/maxfiylik) va uning API'si —
 *  camera-api/app/routers/privacy.py bilan maydonma-maydon mos. */

export interface RetentionSettings {
  eventRetentionDays: number;
  snapshotRetentionDays: number;
  auditLogRetentionDays: number;
  biometricRetentionDaysAfterInactive: number;
  accessEventRetentionDays: number;
  notificationLogRetentionDays: number;
  presenceVisitRetentionDays?: number;
  unknownSightingRetentionDays?: number;
  /** Video arxivi — soatda (disk byudjeti bilan o‘lchanadi). */
  recordingRetentionHours: number;
  eventClipRetentionDays: number;
}

export interface PrivacyOverview {
  peopleTotal: number;
  peopleActive: number;
  peopleInactive: number;
  withBiometrics: number;
  biometricsWithoutConsent: number;
  consentOutdated: number;
  inactiveWithBiometrics: number;
  nextBiometricPurgeAt: string | null;
  biometricPurgeOverdue: number;
  snapshotCount: number;
  oldestSnapshotAt: string | null;
  consentVersion: string;
  consentRequired: boolean;
  retention: RetentionSettings;
}

export interface PrivacyPerson {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim' | string;
  groupOrPosition: string;
  facultyName: string | null;
  active: boolean;
  deactivatedAt: string | null;
  hasBiometrics: boolean;
  biometricsStatus: string;
  consentGivenAt: string | null;
  consentVersion: string | null;
  consentSource: string | null;
  consentCurrent: boolean;
  biometricPurgeAt: string | null;
}

/** GET /api/privacy/people/{id}/biometrics — odam haqida saqlanayotgan biometrika. */
export interface PrivacyBiometrics {
  person: PrivacyPerson;
  photoUrl: string | null;
  photoLeftUrl?: string | null;
  photoRightUrl?: string | null;
  faceTemplateStored: boolean;
  biometricsConfirmedAt: string | null;
  gallerySamples: number;
  linkedSightings: number;
  recentDays: number;
  recentVisits: number;
  recentSightings: number;
  lastSeenAt: string | null;
}

export interface ErasureResult {
  person: PrivacyPerson;
  photoDeleted: boolean;
}

export type PrivacyFilter = 'no_consent' | 'inactive' | 'with_biometrics';
export type ConsentSource = 'qogoz' | 'admin';

export const PRIVACY_FILTER_LABELS: Record<PrivacyFilter, string> = {
  no_consent: "Rozilik yo'q",
  inactive: 'Faol emas',
  with_biometrics: 'Biometrikasi bor',
};

export const CONSENT_SOURCE_LABELS: Record<string, string> = {
  royxatdan_otish: "Ro'yxatdan o'tishda",
  qogoz: "Qog'ozda",
  admin: 'Administrator',
  hemis: 'HEMIS',
};

/** Ro'yxat so'rovi POST bilan ketadi — qidiruv matni JSHSHIR bo'lishi
 *  mumkin va u URL/access logga tushmasligi kerak. */
export const PRIVACY_PEOPLE_SEARCH_PATH = '/api/privacy/people/search';

export function fetchPrivacyOverview(token: string | null, signal?: AbortSignal): Promise<PrivacyOverview> {
  return api.get<PrivacyOverview>('/api/privacy/overview', token, { signal });
}

export function searchPrivacyPeople(
  token: string | null,
  params: { search?: string; filter?: PrivacyFilter | null; page?: number; pageSize?: number },
  signal?: AbortSignal,
): Promise<Page<PrivacyPerson>> {
  return api.post<Page<PrivacyPerson>>(
    PRIVACY_PEOPLE_SEARCH_PATH,
    { search: params.search?.trim() || null, filter: params.filter ?? null, page: params.page ?? 1, pageSize: params.pageSize ?? 20 },
    token,
    { signal },
  );
}

export function fetchPersonBiometrics(token: string | null, personId: string, signal?: AbortSignal): Promise<PrivacyBiometrics> {
  return api.get<PrivacyBiometrics>(`/api/privacy/people/${personId}/biometrics`, token, { signal });
}

export function recordConsent(
  token: string | null,
  personId: string,
  source: ConsentSource,
  note?: string,
): Promise<PrivacyPerson> {
  return api.post<PrivacyPerson>(`/api/privacy/people/${personId}/consent`, { source, note: note || null }, token);
}

export async function withdrawConsent(token: string | null, personId: string): Promise<ErasureResult> {
  // api.del javob tanasini tashlab yuboradi, bu yerda esa natija (rasm
  // ombordan o'chdimi) kerak — shuning uchun so'rov to'g'ridan-to'g'ri.
  const res = await fetch(`${config.apiBaseUrl}/api/privacy/people/${personId}/consent`, {
    method: 'DELETE',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = `So'rov muvaffaqiyatsiz tugadi (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* javob JSON emas */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<ErasureResult>;
}

export function setPersonActive(token: string | null, personId: string, active: boolean): Promise<PrivacyPerson> {
  return api.post<PrivacyPerson>(`/api/privacy/people/${personId}/${active ? 'activate' : 'deactivate'}`, {}, token);
}

export function eraseBiometrics(token: string | null, personId: string): Promise<ErasureResult> {
  return api.post<ErasureResult>(`/api/privacy/people/${personId}/erase-biometrics`, {}, token);
}

export function exportPersonData(token: string | null, personId: string): Promise<Blob> {
  return api.blob(`/api/privacy/people/${personId}/export`, token);
}

// ---------------------------------------------------------------------------
// Sof mantiq (privacyApi.test.ts)
// ---------------------------------------------------------------------------

export type ConsentState = 'current' | 'outdated' | 'missing' | 'not_needed';

/** Rozilik holati: biometrikasi yo'q odamga biometrik rozilik kerak emas;
 *  eski matn versiyasiga berilgan rozilik "eskirgan". */
export function consentState(person: Pick<PrivacyPerson, 'hasBiometrics' | 'consentGivenAt' | 'consentCurrent'>): ConsentState {
  if (person.consentGivenAt) return person.consentCurrent ? 'current' : 'outdated';
  return person.hasBiometrics ? 'missing' : 'not_needed';
}

/** "30 kun", 0 — "Cheklanmagan" (yoki berilgan matn). */
export function formatRetentionDays(days: number, zeroLabel = 'Cheklanmagan'): string {
  if (!days || days <= 0) return zeroLabel;
  if (days % 365 === 0) return `${days / 365} yil`;
  return `${days} kun`;
}

/** Video arxivi muddati: "4 soat", 48 → "2 kun"; 0 — "Saqlanmaydi". */
export function formatRetentionHours(hours: number, zeroLabel = 'Saqlanmaydi'): string {
  if (!hours || hours <= 0) return zeroLabel;
  if (hours % 24 === 0) return `${hours / 24} kun`;
  return `${hours} soat`;
}

/** "19.09.2026" — Toshkent vaqti bo'yicha. */
export function formatUzDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Tashkent',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
}

/** Sanagacha necha kun qoldi (o'tgan bo'lsa manfiy). */
export function daysUntil(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return null;
  return Math.ceil((target - now.getTime()) / 86_400_000);
}

/** Tasdiqlash uchun yoziladigan so'z: odamning familiyasi (birinchi so'z).
 *  To'liq ismni yozdirish ortiqcha, lekin "ha" bosib yuborishdan kuchliroq. */
export function confirmationWord(fullName: string): string {
  const first = fullName.trim().split(/\s+/)[0] ?? '';
  return first || "O'CHIRISH";
}

export function matchesConfirmation(typed: string, expected: string): boolean {
  return typed.trim().toLocaleLowerCase('uz') === expected.trim().toLocaleLowerCase('uz') && expected.trim() !== '';
}

export function exportFilename(person: Pick<PrivacyPerson, 'fullName' | 'id'>, now: Date = new Date()): string {
  const slug = person.fullName
    .trim()
    .toLowerCase()
    .replace(/[ʻʼ'`‘’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  const date = calendarDateInTashkent(now);
  return `shaxsiy-malumot-${slug || person.id}-${date}.json`;
}
