import { useEffect, useState } from 'react';
import { DateRangePicker, FilterBar, type DateRangeValue, type FilterFieldEntry } from '../../ui';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import {
  PERIOD_PRESETS,
  courseOptions,
  groupOptions,
  unitOptions,
  type HisobotFilterOptions,
  type HisobotState,
} from '../../lib/hisobotApi';
import MonthPicker from './MonthPicker';

interface ReportFiltersProps {
  state: HisobotState;
  options: HisobotFilterOptions | null;
  onChange: (patch: Partial<HisobotState>) => void;
  onReset: () => void;
}

/** Yuqoridagi filtrlar: davr + bo'limga xos aholi filtrlari + ism qidiruvi.
 *  Talaba: fakultet -> kurs -> guruh. Xodim: bo'linma turi -> bo'linma. */
export default function ReportFilters({ state, options, onChange, onReset }: ReportFiltersProps) {
  const [query, setQuery] = useState(state.q);
  const debounced = useDebouncedValue(query, 350);

  // URL'dan kelgan qiymat (masalan "Tozalash") maydonni ham yangilasin.
  useEffect(() => setQuery(state.q), [state.q]);
  useEffect(() => {
    if (debounced !== state.q) onChange({ q: debounced });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- faqat debounced qiymat o'zgarganda
  }, [debounced]);

  const period: DateRangeValue = { preset: state.preset, from: state.from, to: state.to };
  const students = state.section === 'talabalar';

  const fields: FilterFieldEntry[] = [
    // Davr doim tanlangan bo'ladi, shuning uchun "faol filtr" deb
    // sanalmaydi — ilgari ham sanalmasdi. Oylik tabelda esa erkin
    // oraliq emas, faqat OY tanlanadi: hujjat butun oy uchun tuziladi.
    {
      kind: 'custom',
      render:
        state.view === 'tabel' ? (
          <MonthPicker value={state.month} onChange={(month) => onChange({ month })} />
        ) : (
          <DateRangePicker
            value={period}
            presets={PERIOD_PRESETS}
            onChange={(v) => onChange({ preset: v.preset, from: v.from, to: v.to })}
            showSummary={false}
          />
        ),
    },
    students && {
      kind: 'select',
      label: 'Fakultet:',
      value: state.faculty,
      onChange: (faculty: string) => onChange({ faculty }),
      placeholder: 'Hammasi',
      options: (options?.faculties ?? []).map((f) => ({ value: f.id, label: `${f.name} (${f.count})` })),
    },
    students && {
      kind: 'select',
      label: 'Kurs:',
      value: state.course,
      onChange: (course: string) => onChange({ course }),
      placeholder: 'Hammasi',
      options: courseOptions(options, state.faculty).map((c) => ({ value: String(c), label: `${c}-kurs` })),
    },
    students && {
      kind: 'select',
      label: 'Guruh:',
      value: state.group,
      onChange: (group: string) => onChange({ group }),
      placeholder: 'Hammasi',
      options: groupOptions(options, state.faculty, state.course).map((g) => ({ value: g, label: g })),
    },
    !students && {
      kind: 'select',
      label: 'Turi:',
      value: state.unitKind,
      onChange: (unitKind: string) => onChange({ unitKind }),
      placeholder: 'Hammasi',
      options: (options?.unit_kinds ?? []).map((k) => ({ value: k.id, label: k.label })),
    },
    !students && {
      kind: 'select',
      label: "Bo'linma:",
      value: state.unit,
      onChange: (unit: string) => onChange({ unit }),
      placeholder: 'Hammasi',
      className: 'sm:max-w-xs',
      options: unitOptions(options, state.unitKind).map((u) => ({ value: u.id, label: `${u.name} (${u.count})` })),
    },
    {
      kind: 'search',
      value: query,
      onChange: setQuery,
      placeholder: "F.I.Sh. bo'yicha qidirish",
      className: 'sm:w-56',
    },
  ];

  // Tozalash URL holatini ham tiklashi kerak — sahifa o'zi bajaradi.
  // Qidiruv maydoni esa mahalliy (`query`, debounce bilan): `state.q` hali
  // yozilmagan bo'lsa (350 ms o'tmagan) sahifaning tiklashi uni ko'rmaydi
  // va matn maydonda qolib, bir zumdan keyin filtr qaytib kelardi.
  return (
    <FilterBar
      fields={fields}
      onReset={() => {
        setQuery('');
        onReset();
      }}
    />
  );
}
