import { calendarDateInTashkent } from './uzDate';
/** "Talabalar va Xodimlar" sahifasi va uning yuklab olish oynasi uchun
 *  umumiy filtr qiymatlari — ikkalasi bir xil kalitlardan foydalanishi
 *  shart, aks holda fayl ekrandagi ro'yxatga mos kelmay qoladi. */

export type PersonType = 'xodim' | 'talaba';

export const PERSON_LABELS: Record<PersonType, string> = {
  xodim: 'Xodimlar',
  talaba: 'Talabalar',
};

/** "Ro'yxatdan o'tmaganlar" — yuzi tasdiqlanmagan HAR KIM ("yo'q" ham,
 *  "kutilmoqda" ham). Backend `tasdiqlanmagan` kalitini shunday tushunadi. */
export type StatusFilter = '' | 'tasdiqlangan' | 'tasdiqlanmagan';

export const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: '', label: 'Hammasi' },
  { key: 'tasdiqlangan', label: "Ro'yxatdan o'tganlar" },
  { key: 'tasdiqlanmagan', label: "Ro'yxatdan o'tmaganlar" },
];

/** Fakulteti ko'rsatilmaganlar. Bo'sh satr "filtr yo'q" degani,
 *  shuning uchun alohida kalit kerak. */
export const NO_FACULTY_KEY = '__none__';
export const NO_FACULTY_LABEL = 'Fakultetsiz';

export type ExportKind = 'people' | 'stats';

/** Fayl nomi brauzerda tuziladi: API boshqa domenda va Content-Disposition
 *  sarlavhasi CORS ruxsatisiz skriptga ko'rinmaydi. */
export function exportFilename(kind: ExportKind, type: PersonType, course: number | null, status: StatusFilter): string {
  const date = calendarDateInTashkent(); // YYYY-MM-DD, Toshkent sanasi
  const base = type === 'talaba' ? 'talabalar' : 'xodimlar';
  if (kind === 'stats') return `${base}-statistika-${date}.xlsx`;
  const coursePart = type === 'talaba' && course ? `-${course}-kurs` : '';
  const statusPart =
    status === 'tasdiqlangan' ? '-royxatdan-otganlar' : status === 'tasdiqlanmagan' ? '-royxatdan-otmaganlar' : '';
  return `${base}${coursePart}${statusPart}-${date}.xlsx`;
}
