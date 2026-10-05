export type SortDir = 'asc' | 'desc';

export interface SortState {
  key: string;
  dir: SortDir;
}

export type SortValue = string | number | boolean | Date | null | undefined;

function isEmpty(value: SortValue): boolean {
  return value === null || value === undefined || value === '' || (typeof value === 'number' && Number.isNaN(value));
}

const collator = new Intl.Collator('uz', { numeric: true, sensitivity: 'base' });

/** Ikki qiymatni solishtirish (o'sish tartibida). Bo'sh qiymatlar bu yerda
 *  hisobga olinmaydi — ular sortRows'da doim oxiriga qo'yiladi. */
export function compareValues(a: SortValue, b: SortValue): number {
  if (a instanceof Date || b instanceof Date) {
    return (a instanceof Date ? a.getTime() : Number(a)) - (b instanceof Date ? b.getTime() : Number(b));
  }
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);
  return collator.compare(String(a), String(b));
}

/** Qatorlarni saralash: barqaror (teng qatorlar tartibi saqlanadi), bo'sh
 *  qiymatlar yo'nalishdan qat'i nazar oxirida, raqamlar raqam sifatida,
 *  matnlar o'zbekcha/raqamli tartibda ("Guruh 2" < "Guruh 10"). */
export function sortRows<T>(rows: readonly T[], getValue: (row: T) => SortValue, dir: SortDir): T[] {
  const factor = dir === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: getValue(row) }))
    .sort((x, y) => {
      const xEmpty = isEmpty(x.value);
      const yEmpty = isEmpty(y.value);
      if (xEmpty && yEmpty) return x.index - y.index;
      if (xEmpty) return 1;
      if (yEmpty) return -1;
      return compareValues(x.value, y.value) * factor || x.index - y.index;
    })
    .map((item) => item.row);
}

/** Sarlavha bosilganda: yo'q → o'sish → kamayish → yo'q. */
export function nextSort(current: SortState | null, key: string, firstDir: SortDir = 'asc'): SortState | null {
  if (!current || current.key !== key) return { key, dir: firstDir };
  if (current.dir === firstDir) return { key, dir: firstDir === 'asc' ? 'desc' : 'asc' };
  return null;
}
