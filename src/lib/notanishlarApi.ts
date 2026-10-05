import { api, buildQuery, type CallOptions } from './apiClient';

/** Kunduzgi notanish yuzlar (camera-api/app/routers/unknown_sightings.py). */

export type SightingStatus = 'kutilmoqda' | 'talaba' | 'begona' | 'otkazildi';

export interface Sighting {
  id: string;
  day: string;
  cameraId: string | null;
  cameraName: string | null;
  firstSeenAt: string;
  lastSeenAt: string;
  /** Bugun necha marta ko'ringan — ko'p bo'lsa, ehtimol talaba. */
  hits: number;
  cropUrl: string | null;
  facePx: number;
  closestSimilarity: number | null;
  status: SightingStatus;
  personId: string | null;
  personName: string | null;
}

export interface SightingList {
  items: Sighting[];
  total: number;
  pending: number;
  day: string;
}

export interface ResolveResult {
  item: Sighting;
  message: string;
}

export function getSightings(
  params: { sana?: string; holat?: SightingStatus | 'hammasi'; limit?: number },
  opts: CallOptions = {},
): Promise<SightingList> {
  return api.get<SightingList>(`/api/notanishlar${buildQuery(params)}`, undefined, opts);
}

/** Takroriy notanish — bir odamning bir necha kundagi yuzlari
 *  (camera-api/app/services/unknown_clusters.py). */
export interface RecurringHint {
  personId: string;
  fullName: string;
  groupOrPosition: string;
  similarity: number;
}

export interface RecurringUnknown {
  key: string;
  sightingIds: string[];
  /** Necha xil kunda ko'ringan — ko'p bo'lsa, bu yerning odami (talaba/xodim). */
  days: number;
  hits: number;
  cameras: string[];
  firstSeenAt: string;
  lastSeenAt: string;
  facePx: number;
  cropUrls: string[];
  /** Ro'yxatdagi o'xshash odamlar — "bu X emasmi?" ishorasi. */
  hints: RecurringHint[];
}

export interface RecurringList {
  items: RecurringUnknown[];
  pending: number;
}

export interface GroupActionResult {
  message: string;
  count: number;
}

export function getRecurringUnknowns(params: { kun?: number; min_kun?: number; limit?: number } = {}, opts: CallOptions = {}): Promise<RecurringList> {
  return api.get<RecurringList>(`/api/notanishlar/takroriy${buildQuery(params)}`, undefined, opts);
}

export function assignRecurring(sightingIds: string[], personId: string): Promise<GroupActionResult> {
  return api.post<GroupActionResult>('/api/notanishlar/takroriy/biriktirish', { sightingIds, personId });
}

export function dismissRecurring(sightingIds: string[]): Promise<GroupActionResult> {
  return api.post<GroupActionResult>('/api/notanishlar/takroriy/otkazish', { sightingIds });
}

/** Yuzni kimga biriktirish — reviewEvents bilan ishlaydigan qisqa qidiruv. */
export interface PersonPick {
  id: string;
  fullName: string;
  groupOrPosition: string;
  biometricsStatus: string;
}

export function pickPeople(q: string, limit = 8, opts: CallOptions = {}): Promise<PersonPick[]> {
  return api.get<PersonPick[]>(`/api/notanishlar/odamlar${buildQuery({ q, limit })}`, undefined, opts);
}

export function assignSighting(id: string, personId: string): Promise<ResolveResult> {
  return api.post<ResolveResult>(`/api/notanishlar/${encodeURIComponent(id)}/talaba`, { personId });
}

export function markStranger(id: string): Promise<ResolveResult> {
  return api.post<ResolveResult>(`/api/notanishlar/${encodeURIComponent(id)}/begona`, {});
}

export function dismissSighting(id: string): Promise<ResolveResult> {
  return api.post<ResolveResult>(`/api/notanishlar/${encodeURIComponent(id)}/otkazish`, {});
}

/** "11:42" — Toshkent vaqtida. */
export function sightingTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('uz-UZ', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Tashkent',
    }).format(new Date(iso));
  } catch {
    return iso.slice(11, 16);
  }
}

/** Ro'yxatdagi eng yaqin odamga o'xshashlik — operatorga ishora.
 *  Yuqori bo'lsa: ehtimol tanish odam, lekin yomon burchakdan. */
export function likelihoodHint(similarity: number | null): string | null {
  if (similarity === null) return null;
  if (similarity >= 0.35) return 'Kimgadir o‘xshaydi';
  return null;
}
