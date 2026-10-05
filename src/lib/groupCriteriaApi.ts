import { api, buildQuery, type CallOptions } from './apiClient';

/**
 * Nazorat → guruh: har talaba qatorida hamma kriteriyalar
 * (GET /api/situation/group-criteria — hisobot bilan bir xil hisob, Nazorat
 * ruxsati bilan, hisobotlar parolisiz).
 */

export type CriterionTone = 'success' | 'warning' | 'danger' | 'neutral';

export interface GroupCriterion {
  key: string;
  /** Buyurtmachi ro'yxatidagi raqam (6, 7, 8, 9, 10, 15, 19 ...). */
  code: number | null;
  label: string;
  description: string;
  /** Guruh bo'yicha qisqa ko'rsatkich ("83%", "4", "—"). */
  indicator: string;
  tone: CriterionTone;
  /** Hisoblanmasa — sababi (0 o'rniga). */
  unavailable: string | null;
  note: string | null;
}

export interface CriterionCell {
  value: string;
  tone: CriterionTone;
  title: string;
  /** 2 daqiqalik video dalillar soni. */
  evidence: number | null;
}

export interface GroupCriteriaPerson {
  id: string;
  full_name: string;
  initials: string;
  enrolled: boolean;
  cells: Record<string, CriterionCell>;
}

export interface GroupCriteria {
  group: string;
  period: { from: string; to: string; days: number };
  /** Shu kun(lar) uchun kunlik video tahlil natijasi bormi. */
  analysed: boolean;
  criteria: GroupCriterion[];
  people: GroupCriteriaPerson[];
}

export function getGroupCriteria(group: string, date: string, opts?: CallOptions): Promise<GroupCriteria> {
  return api.get<GroupCriteria>(`/api/situation/group-criteria${buildQuery({ group, date })}`, undefined, opts);
}

/** Jadval ustuni uchun qisqa nom (to'liq nomi — sarlavha izohida). */
export const CRITERION_SHORT: Record<string, string> = {
  davomat: 'Davomat',
  kechikish: 'Kechikish',
  dars_qatnashish: 'Darsda',
  darsga_kech: 'Darsga kech',
  darsdan_erta: 'Erta chiqdi',
  forma: 'Oq xalat',
  chekish: 'Chekish',
  diqqat: 'Diqqat',
  erta_ketish: 'Erta ketdi',
  dars_otkazish: 'Darsga kirdi',
  faollik: 'Faollik',
};

export function criterionShort(c: Pick<GroupCriterion, 'key' | 'label'>): string {
  return CRITERION_SHORT[c.key] ?? c.label;
}

export const TONE_TEXT: Record<CriterionTone, string> = {
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-muted',
};
