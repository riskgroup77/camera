import { ChevronLeft, ChevronRight } from 'lucide-react';
import { IconButton, Select } from '../../ui';
import { UZ_MONTHS, isMonth, monthOf, todayInTashkent } from '../../lib/uzDate';

export interface MonthPickerProps {
  /** "YYYY-MM". */
  value: string;
  onChange: (month: string) => void;
  /** Kelajakdagi oylar tanlanmasin: standart — joriy oy. */
  max?: string;
  /** Ro'yxatdagi eng eski yil (standart: joriy yildan 3 yil oldin). */
  years?: number;
}

/** "2026-09" ga oy qo'shish/ayirish. */
function shiftMonth(month: string, delta: number): string {
  const year = Number(month.slice(0, 4));
  const index = Number(month.slice(5, 7)) - 1 + delta;
  const next = new Date(Date.UTC(year, index, 1));
  return monthOf(next.toISOString().slice(0, 10));
}

/**
 * Oy tanlagichi — tabel ko'rinishida erkin sana oralig'i o'rnida.
 *
 * Tabel har doim BUTUN oy bo'yicha tuziladi (hujjat shunday imzolanadi),
 * shuning uchun "dan–gacha" emas, faqat oy tanlanadi. Yon tugmalar —
 * eng ko'p ishlatiladigan harakat: bir oy oldinga/orqaga.
 */
export default function MonthPicker({ value, onChange, max = monthOf(todayInTashkent()), years = 4 }: MonthPickerProps) {
  const month = isMonth(value) ? value : max;
  const currentYear = Number(max.slice(0, 4));
  const yearList: number[] = [];
  for (let y = currentYear - (years - 1); y <= currentYear; y += 1) yearList.push(y);
  // Tanlangan yil ro'yxatdan tashqarida bo'lsa (ulashilgan havola) — qo'shiladi.
  const selectedYear = Number(month.slice(0, 4));
  if (!yearList.includes(selectedYear)) yearList.push(selectedYear);
  yearList.sort((a, b) => a - b);

  const previous = shiftMonth(month, -1);
  const next = shiftMonth(month, 1);
  const canGoNext = next <= max;
  // Ro'yxatdagi eng eski yildan orqaga o'tib bo'lmaydi: ilgari "Oldingi
  // oy" tugmasi cheksiz edi va tasodifan 2019-yilga tushib qolgan
  // foydalanuvchi tanlangan yilni ro'yxatda ko'rib, nega bo'sh tabel
  // chiqayotganini tushunmasdi.
  const minMonth = `${yearList[0]}-01`;
  const canGoPrev = previous >= minMonth;

  function setPart(part: 'year' | 'month', raw: string) {
    const candidate = part === 'year' ? `${raw}-${month.slice(5, 7)}` : `${month.slice(0, 4)}-${raw}`;
    onChange(candidate > max ? max : candidate);
  }

  return (
    <div className="inline-flex items-center gap-1.5">
      <IconButton
        icon={ChevronLeft}
        label="Oldingi oy"
        title={canGoPrev ? 'Oldingi oy' : `${yearList[0]}-yildan oldingi tabel saqlanmaydi`}
        onClick={() => onChange(previous)}
        size="sm"
        disabled={!canGoPrev}
      />
      <Select
        value={month.slice(5, 7)}
        onChange={(m) => setPart('month', m)}
        ariaLabel="Oy"
        // Kelajakdagi oy tanlanmaydi: ilgari ro'yxatdan "Dekabr" tanlansa
        // qiymat jimgina joriy oyga qaytarilardi va foydalanuvchi
        // tanlagani "yo'qolib" qolardi. Endi bunday variantlar o'chiq.
        options={UZ_MONTHS.map((name, index) => {
          const value = String(index + 1).padStart(2, '0');
          return {
            value,
            label: `${name[0].toUpperCase()}${name.slice(1)}`,
            disabled: `${month.slice(0, 4)}-${value}` > max,
          };
        })}
      />
      <Select
        value={month.slice(0, 4)}
        onChange={(y) => setPart('year', y)}
        ariaLabel="Yil"
        options={yearList.map((y) => ({ value: String(y), label: String(y) }))}
      />
      <IconButton
        icon={ChevronRight}
        label="Keyingi oy"
        // Nega o'chiq ekani sichqoncha ostida yozilib tursin.
        title={canGoNext ? 'Keyingi oy' : "Kelajakdagi oy uchun tabel tuzilmaydi"}
        onClick={() => onChange(next)}
        size="sm"
        disabled={!canGoNext}
      />
    </div>
  );
}
