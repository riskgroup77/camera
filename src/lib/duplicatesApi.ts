import { api } from './apiClient';

/** Talaba/xodim dublikatlari (camera-api/app/services/person_dedupe.py). */

export interface DuplicatePerson {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  groupOrPosition: string;
  /** JSHSHIR raqamining o'zi yuborilmaydi — faqat bor/yo'qligi. */
  hasPinfl: boolean;
  biometricsStatus: 'tasdiqlangan' | 'kutilmoqda' | 'yoq';
  selfRegistered: boolean;
  attendance: number;
  createdAt: string | null;
  photoUrl?: string | null;
}

export interface DuplicateGroup {
  keeper: DuplicatePerson;
  duplicates: DuplicatePerson[];
  /** ism — ism bo'yicha; ism_yuz — yuzi ham mos; yuz — yuzi bir xil, ismi boshqa (faqat ko'rib chiqish). */
  reason?: 'ism' | 'ism_yuz' | 'yuz';
  faceSimilarity?: number | null;
  mergeable?: boolean;
}

export interface MergeResult {
  mergedGroups: number;
  removed: number;
  errors: string[];
}

export function getDuplicates(): Promise<DuplicateGroup[]> {
  return api.get<DuplicateGroup[]>('/api/students-staff/dublikatlar');
}

export function mergeDuplicates(groups: { keepId: string; removeIds: string[] }[]): Promise<MergeResult> {
  return api.post<MergeResult>('/api/students-staff/dublikatlar/birlashtirish', { groups });
}
