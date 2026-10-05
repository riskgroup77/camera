import { api, buildQuery, type CallOptions } from './apiClient';
import { rag, type Rag } from '../ui/rag';

/** Yuz tekshiruvi navbati va o'lchangan aniqlik (camera-api/app/routers/face_review.py). */

export type ReviewStatus = 'kutilmoqda' | 'tasdiqlandi' | 'rad_etildi';

export interface ReviewItem {
  id: string;
  day: string;
  cameraId: string | null;
  cameraName: string | null;
  personId: string;
  personName: string;
  personType: string;
  group: string;
  /** Ro'yxatdagi (hujjat) rasmi. */
  photoUrl: string | null;
  /** Kamera kadridan kesilgan yuz. */
  cropUrl: string | null;
  similarity: number;
  secondSimilarity: number | null;
  hits: number;
  facePx: number;
  firstSeenAt: string;
  lastSeenAt: string;
  status: ReviewStatus;
}

export interface ReviewList {
  items: ReviewItem[];
  pending: number;
  day: string;
}

export interface ResolveResult {
  id: string;
  status: ReviewStatus;
  message: string;
  galleryAdded: boolean;
  attendanceStatus: string | null;
}

export interface ModuleAccuracy {
  code: number;
  name: string;
  confirmed: number;
  rejected: number;
  pending: number;
  /** 0..1, qaror bo'lmasa null. */
  precision: number | null;
}

export interface Coverage {
  enrolled: number;
  total: number;
  ratio: number | null;
}

export interface Accuracy {
  days: number;
  modules: ModuleAccuracy[];
  queue: { confirmed: number; rejected: number; pending: number; confirmRate: number | null };
  students: Coverage;
  staff: Coverage;
  recognizedToday: number;
  enrolledTodayRatio: number | null;
}

export function getReviewQueue(
  params: { sana?: string; holat?: ReviewStatus | 'hammasi'; limit?: number },
  opts: CallOptions = {},
): Promise<ReviewList> {
  return api.get<ReviewList>(`/api/tekshiruv${buildQuery(params)}`, undefined, opts);
}

export function confirmReview(id: string): Promise<ResolveResult> {
  return api.post<ResolveResult>(`/api/tekshiruv/${encodeURIComponent(id)}/tasdiqlash`, {});
}

export function rejectReview(id: string): Promise<ResolveResult> {
  return api.post<ResolveResult>(`/api/tekshiruv/${encodeURIComponent(id)}/rad`, {});
}

export function accuracyPath(days = 30): string {
  return `/api/tekshiruv/aniqlik${buildQuery({ kun: days })}`;
}

/** 0.463 -> "46%"; null -> "—". */
export function percent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—';
  return `${Math.round(ratio * 100)}%`;
}

/** Aniqlik svetofori: 90% dan yashil, 75% dan sariq. Kam qarorli (< 5)
 *  modulga rang berilmaydi — 1 tadan 1 "100%" hech narsani o'lchamaydi. */
export function precisionRag(item: Pick<ModuleAccuracy, 'confirmed' | 'rejected' | 'precision'>): Rag {
  if (item.confirmed + item.rejected < 5 || item.precision === null) return 'yoq';
  return rag(item.precision * 100, { ok: 90, warn: 75 });
}

export type ReviewKeyAction = 'confirm' | 'reject' | 'next' | 'prev';

/** Klaviatura: T — "Ha, u", R — "Yo'q", strelka/J/K — navbatda yurish.
 *  Kirill tartibidagi klavish ham ishlaydi (Е/К — o'sha tugmalar). */
export function reviewKeyAction(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey'>): ReviewKeyAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  switch (event.key.toLowerCase()) {
    case 't':
    case 'е':
      return 'confirm';
    case 'r':
    case 'к':
      return 'reject';
    case 'arrowright':
    case 'arrowdown':
    case 'j':
      return 'next';
    case 'arrowleft':
    case 'arrowup':
    case 'k':
      return 'prev';
    default:
      return null;
  }
}

/** Qator o'chirilgandan keyin tanlov qayerda qoladi: o'sha o'rinda
 *  (keyingisi ko'tariladi), oxirgisi o'chsa — bittasi oldinga. */
export function indexAfterRemoval(index: number, lengthAfter: number): number {
  if (lengthAfter <= 0) return 0;
  return Math.min(Math.max(0, index), lengthAfter - 1);
}
