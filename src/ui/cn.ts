/** Sinf nomlarini birlashtirish: `cn('a', cond && 'b', undefined)` → "a b". */
export function cn(...parts: Array<string | false | null | undefined | 0>): string {
  return parts.filter(Boolean).join(' ');
}

/** Barcha interaktiv elementlar uchun yagona fokus halqasi (klaviatura bilan). */
export const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45 focus-visible:ring-offset-1 focus-visible:ring-offset-surface';

/** Kiritish maydonlari (input/select) uchun umumiy ko'rinish.
 *  To'rtburchak, soyasiz — faqat 1px chiziq. Monoshriftni qo'shuvchi
 *  `intel-code` ALOHIDA qo'yiladi: qidiruv, sana va tanlov maydonlari
 *  o'lchov kiritadi, Textarea esa erkin matn (sans) uchun qoladi. */
export const controlBase =
  'w-full rounded-control border border-border bg-surface text-fg outline-none transition-colors placeholder:text-subtle placeholder:tracking-normal hover:border-border-strong focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60';

/** Boshqaruv balandliklari: 28 / 32 / 34 px — ish asbobi zichligi,
 *  lekin barmoq uchun eng kichigi ham 28px. */
export const controlSizes = {
  sm: 'h-7 px-2 text-[12px]',
  md: 'h-8 px-2.5 text-[13px]',
  lg: 'h-[34px] px-3 text-[14px]',
} as const;

export type ControlSize = keyof typeof controlSizes;
