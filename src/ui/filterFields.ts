import type { ReactNode } from 'react';
import type { SelectOption } from './Select';

/* Filtr maydonlari — sof mantiq (komponentsiz, shuning uchun alohida
 * fayl: urlTab.ts / tones.ts kabi).
 *
 * `Toolbar` faqat tashqi ko'rinishni bergani uchun har sahifa "nechta
 * filtr faol" va "tozalash nimani nolga qaytaradi" mantig'ini o'zi
 * yozardi — oltita sahifada oltita nusxa, va ular bir-biridan farq
 * qilib ketgandi (biri `search`ni trim qilardi, biri qilmasdi; biri
 * "hammasi" qiymatini '' deb, biri 'all' deb hisoblardi).
 *
 * Sahifa o'z holatini va URL parametrlarini o'zi boshqarishda davom
 * etadi — bu yerga faqat qiymat va `onChange` uzatiladi. */

/** Qidiruv maydoni — bo'sh bo'lmasa faol. */
export interface SearchFilterField {
  kind: 'search';
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
}

/** Tanlov — `inactiveValue`dan farqli bo'lsa faol (standart: bo'sh satr). */
export interface SelectFilterField {
  kind: 'select';
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  placeholder?: string;
  /** Chap tomondagi yozuv ("Muhimlik:"). */
  label?: string;
  ariaLabel?: string;
  className?: string;
  /** "Hammasi" degani — shu qiymatda filtr faol emas. */
  inactiveValue?: string;
}

/** O'ziga xos boshqaruv (sana oralig'i, segmentli tablar...) — faolligini
 *  va tozalashini sahifa o'zi aytadi. */
export interface CustomFilterField {
  kind: 'custom';
  render: ReactNode;
  active?: boolean;
  /** "Tozalash" bosilganda. Berilmasa bu maydon tozalanmaydi. */
  onClear?: () => void;
}

export type FilterField = SearchFilterField | SelectFilterField | CustomFilterField;

/** Ro'yxatda shart bilan o'chirilgan maydonlar bo'lishi mumkin:
 *  `isStudents && { kind: 'select', ... }`. */
export type FilterFieldEntry = FilterField | false | null | undefined;

/** `false`/`null` yozuvlarni tashlab, faqat haqiqiy maydonlarni qaytaradi. */
export function presentFilterFields(fields: readonly FilterFieldEntry[]): FilterField[] {
  return fields.filter((entry): entry is FilterField => Boolean(entry));
}

/** Maydon faolmi (foydalanuvchi standart holatdan chetga chiqqanmi). */
export function isFilterActive(field: FilterField): boolean {
  if (field.kind === 'search') return field.value.trim() !== '';
  if (field.kind === 'select') return field.value !== (field.inactiveValue ?? '');
  return field.active === true;
}

/** Faol filtrlar soni — "Tozalash (n)" shu sondan. */
export function filterActiveCount(fields: readonly FilterFieldEntry[]): number {
  return presentFilterFields(fields).filter(isFilterActive).length;
}

/** Har bir maydonni standart holatiga qaytaradi. */
export function resetFilterFields(fields: readonly FilterFieldEntry[]): void {
  for (const field of presentFilterFields(fields)) {
    if (field.kind === 'search') field.onChange('');
    else if (field.kind === 'select') field.onChange(field.inactiveValue ?? '');
    else field.onClear?.();
  }
}
