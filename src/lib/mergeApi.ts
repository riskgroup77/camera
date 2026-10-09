import { api } from './apiClient';

/** Qo'lda birlashtirish (camera-api/app/services/person_dedupe.py merge_manual).
 *  Administrator ikki yozuvni o'zi tanlaydi — avtomatik "Dublikatlar" topa
 *  olmaydigan juftlar: familiya o'zgargan, harf xatosi, kirill/lotin. */

export interface MergeCard {
  id: string;
  fullName: string;
  groupOrPosition: string;
  faculty: string;
  active: boolean;
  biometricsStatus: 'tasdiqlangan' | 'kutilmoqda' | 'yoq';
  allAngles: boolean;
  /** JSHSHIR raqamining o'zi yuborilmaydi — faqat bor/yo'qligi. */
  hasPinfl: boolean;
  hemisLinked: boolean;
  selfRegistered: boolean;
  attendance: number;
  lessons: number;
  createdAt: string | null;
  photoUrl?: string | null;
}

export interface MergeResultCard {
  fullName: string;
  groupOrPosition: string;
  faculty: string;
  active: boolean;
  biometricsStatus: 'tasdiqlangan' | 'kutilmoqda' | 'yoq';
  allAngles: boolean;
  hasPinfl: boolean;
  hemisLinked: boolean;
  attendance: number;
}

export interface MergePlan {
  /** Qoladigan yozuv (yuzi tasdiqlangani). */
  keep: MergeCard;
  /** Ma'lumoti ko'chib, o'chiriladigan yozuv. */
  remove: MergeCard;
  result: MergeResultCard;
  applied: boolean;
  moved: Record<string, number>;
}

/** Qidiruv tanada — JSHSHIR URL/access logga tushmaydi. */
export function getMergeCandidates(personId: string, search: string, signal?: AbortSignal): Promise<MergeCard[]> {
  return api.post<MergeCard[]>(
    `/api/students-staff/${personId}/birlashtirish-nomzodlari`,
    { search: search.trim() || null },
    undefined,
    { signal },
  );
}

export function mergeTwo(firstId: string, secondId: string, apply: boolean): Promise<MergePlan> {
  return api.post<MergePlan>('/api/students-staff/qolda-birlashtirish', { firstId, secondId, apply });
}
