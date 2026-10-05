import { api } from './apiClient';

export interface PersonLocation {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  faculty: string | null;
  groupOrPosition: string;
  initials: string;
  cameraId: string | null;
  cameraName: string | null;
  building: string | null;
  floor: number | null;
  zone: string | null;
  lastSeenAt: string | null;
  currentlyVisible: boolean;
  /** Yuzi tasdiqlangan — kameralar taniy oladi. */
  hasFace?: boolean;
  photoUrl?: string | null;
}

export interface PhotoPersonMatch {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  groupOrPosition: string;
  similarity: number;
  photoUrl: string | null;
  lastSeenAt: string | null;
}

export interface PhotoSightingMatch {
  id: string;
  similarity: number;
  cropUrl: string | null;
  cameraId: string | null;
  cameraName: string | null;
  firstSeenAt: string;
  lastSeenAt: string;
  hits: number;
}

export interface PhotoSearchResult {
  people: PhotoPersonMatch[];
  sightings: PhotoSightingMatch[];
  dateFrom: string;
  dateTo: string;
}

export interface RouteStop {
  cameraId: string | null;
  cameraName: string | null;
  building: string | null;
  floor: number | null;
  zone: string | null;
  startedAt: string;
  endedAt: string;
  count: number;
  bestSimilarity: number | null;
}

export interface PersonRoute {
  personId: string;
  fullName: string;
  day: string;
  stops: RouteStop[];
}

export function searchPersonLocation(query: string, signal?: AbortSignal): Promise<PersonLocation[]> {
  return api.post<PersonLocation[]>('/api/person-locator/search', { query, limit: 12 }, null, { signal });
}

export interface PhotoSearchParams {
  from: string;
  to: string;
  min: number;
}

export function searchByPhoto(photo: File, params: PhotoSearchParams, signal?: AbortSignal): Promise<PhotoSearchResult> {
  const form = new FormData();
  form.append('photo', photo);
  form.append('dan', params.from);
  form.append('gacha', params.to);
  form.append('min', String(params.min));
  return api.postForm<PhotoSearchResult>('/api/person-locator/rasm', form, null, { signal });
}

export function getPersonRoute(personId: string, day: string, signal?: AbortSignal): Promise<PersonRoute> {
  return api.get<PersonRoute>(`/api/person-locator/${encodeURIComponent(personId)}/yol?sana=${encodeURIComponent(day)}`, null, { signal });
}

export function locationText(person: PersonLocation): string | null {
  if (!person.cameraName) return null;
  const place = [person.building, person.floor == null ? null : `${person.floor}-qavat`, person.zone].filter(Boolean);
  return [person.cameraName, place.join(' · ')].filter(Boolean).join(' · ');
}

/** Video devor faqat `kamera` parametrini o'qiydi — bino/qavat berilsa
 *  ham e'tiborsiz qolardi, shuning uchun havola faqat kamera bilan. */
export function liveLink(cameraId: string): string {
  return `/videodevor?${new URLSearchParams({ kamera: cameraId }).toString()}`;
}

export function similarityPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

const TIME_FORMAT = new Intl.DateTimeFormat('uz-UZ', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Tashkent' });

export function clockTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : TIME_FORMAT.format(date);
}

/** "09:00–09:05"; bir daqiqa ichida bo'lsa bitta vaqt. */
export function stopTimeRange(stop: Pick<RouteStop, 'startedAt' | 'endedAt'>): string {
  const from = clockTime(stop.startedAt);
  const to = clockTime(stop.endedAt);
  return from === to ? from : `${from}–${to}`;
}

/** To'xtash davomiyligi: "4 daq", "1 soat 5 daq"; bir daqiqadan kam — null. */
export function stopDuration(stop: Pick<RouteStop, 'startedAt' | 'endedAt'>): string | null {
  const minutes = Math.round((Date.parse(stop.endedAt) - Date.parse(stop.startedAt)) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 1) return null;
  if (minutes < 60) return `${minutes} daq`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} soat ${rest} daq` : `${hours} soat`;
}

export function stopPlace(stop: Pick<RouteStop, 'building' | 'floor' | 'zone'>): string | null {
  const parts = [stop.building, stop.floor == null ? null : `${stop.floor}-qavat`, stop.zone].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}
