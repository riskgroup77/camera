import type { AIModuleGroup } from '../types';

/**
 * TT hujjatidagi 25 ta AI kriteriyasining guruh nomlari.
 *
 * Ilgari bu src/mock/admin.ts ichida turardi va production sahifalari
 * (AIModulesPage, AIModuleChecklist) uni o'sha yerdan import qilardi —
 * ya'ni ishlab turgan kod "mock" papkasiga bog'liq edi. Bu qiymatlar
 * soxta ma'lumot emas, doimiy yorliqlar: shuning uchun ular shu yerga,
 * mock'dan tashqariga ko'chirildi.
 */
export const AI_MODULE_GROUP_LABELS: Record<AIModuleGroup, string> = {
  A: 'Kirish-chiqish va hudud xavfsizligi',
  B: 'Davomat va shaxsni aniqlash',
  C: "Forma va tashqi ko'rinish",
  D: 'Xulq-atvor va odob-axloq',
  E: "Ta'lim jarayoni sifati (dars monitoring)",
  F: 'Favqulodda holatlar',
};
