/**
 * Konsolning davomat hisob-kitoblari — SOF funksiyalar (testlari
 * `attendance.test.ts`da).
 *
 * Bitta qoida: foiz HAMMA joyda backenddagi formula bilan hisoblanadi —
 * `present / (present + absent + notYet)`. Ya'ni yuzi ro'yxatdan
 * o'tmagan (noData) va dam olishdagi odam foizni pasaytirmaydi, chunki
 * ular o'lchanmagan. Shuning uchun konsol hech qachon "0%" deb
 * yolg'on gapirmaydi — o'lchanmaganini alohida ko'rsatadi.
 */
import type { AnalyticsDaily, Counts, FacultyCounts, KafedraStat, Overview } from '../lib/situationApi';
import { addDays } from '../lib/uzDate';
import type { Scope } from './consoleFilter';

export const EMPTY_COUNTS: Counts = {
  total: 0,
  enrolled: 0,
  present: 0,
  late: 0,
  absent: 0,
  dayOff: 0,
  notYet: 0,
  noData: 0,
  rate: null,
};

/** Foiz: present / (present + absent + notYet). Asos 0 → null ("—"). */
export function rateOf(counts: Pick<Counts, 'present' | 'absent' | 'notYet'>): number | null {
  const decided = counts.present + counts.absent + counts.notYet;
  if (decided <= 0) return null;
  return Math.round((counts.present / decided) * 1000) / 10;
}

/** Ikki to'plamni qo'shadi va foizni QAYTA hisoblaydi (foizlarni
 *  o'rtachalash noto'g'ri bo'lardi — to'plamlar teng emas). */
export function addCounts(a: Counts, b: Counts): Counts {
  const sum = {
    total: a.total + b.total,
    enrolled: a.enrolled + b.enrolled,
    present: a.present + b.present,
    late: a.late + b.late,
    absent: a.absent + b.absent,
    dayOff: a.dayOff + b.dayOff,
    notYet: a.notYet + b.notYet,
    noData: a.noData + b.noData,
  };
  return { ...sum, rate: rateOf(sum) };
}

/** Filtrga mos kunlik yig'indi. */
export function scopeCounts(overview: Overview | null, scope: Scope): Counts {
  if (!overview) return EMPTY_COUNTS;
  if (scope === 'xodim') return overview.staff;
  if (scope === 'talaba') return overview.students;
  return addCounts(overview.staff, overview.students);
}

export type SegmentKey = 'oz_vaqtida' | 'kech' | 'kelmadi' | 'olchanmagan';

export interface Segment {
  key: SegmentKey;
  label: string;
  value: number;
  /** Jamidagi ulushi, 0–100. Jami 0 bo'lsa — 0. */
  share: number;
  /** Tailwind fon sinfi. */
  solid: string;
  text: string;
}

const SEGMENT_META: Record<SegmentKey, { label: string; solid: string; text: string }> = {
  oz_vaqtida: { label: "O'z vaqtida", solid: 'bg-success', text: 'text-success' },
  kech: { label: 'Kech keldi', solid: 'bg-warning', text: 'text-warning' },
  kelmadi: { label: 'Kelmadi', solid: 'bg-danger', text: 'text-danger' },
  olchanmagan: { label: "O'lchanmagan", solid: 'bg-subtle', text: 'text-subtle' },
};

/**
 * Kunni to'rt bo'lakka ajratadi. Bo'laklar yig'indisi HAR DOIM `total`ga
 * teng: "o'lchanmagan" — hali kelmagan, yuzi yo'q va dam olishdagilar.
 * Shu sabab panelda "qolgani qayerda?" degan savol qolmaydi.
 */
export function breakdown(counts: Counts): Segment[] {
  const onTime = Math.max(0, counts.present - counts.late);
  const unmeasured = counts.notYet + counts.noData + counts.dayOff;
  const total = onTime + counts.late + counts.absent + unmeasured;
  const values: Record<SegmentKey, number> = {
    oz_vaqtida: onTime,
    kech: counts.late,
    kelmadi: counts.absent,
    olchanmagan: unmeasured,
  };
  return (Object.keys(SEGMENT_META) as SegmentKey[]).map((key) => ({
    key,
    ...SEGMENT_META[key],
    value: values[key],
    share: total > 0 ? Math.round((values[key] / total) * 1000) / 10 : 0,
  }));
}

/** Ikki turdagi kunlik qatorlarni sana bo'yicha birlashtiradi. Foiz
 *  qayta hisoblanadi: `present / expected` — backenddagi formula. */
export function mergeDaily(a: readonly AnalyticsDaily[], b: readonly AnalyticsDaily[]): AnalyticsDaily[] {
  const byDate = new Map<string, AnalyticsDaily>();
  for (const row of [...a, ...b]) {
    const current = byDate.get(row.date);
    if (!current) {
      byDate.set(row.date, { ...row });
      continue;
    }
    const present = current.present + row.present;
    const expected = current.expected + row.expected;
    byDate.set(row.date, {
      date: row.date,
      present,
      late: current.late + row.late,
      absent: current.absent + row.absent,
      expected,
      rate: expected > 0 ? Math.round((present / expected) * 1000) / 10 : null,
      // O'rtacha kelish vaqtini qo'shib bo'lmaydi — trend uchun kerak emas.
      avgArrival: null,
    });
  }
  return [...byDate.values()].sort((x, y) => x.date.localeCompare(y.date));
}

/**
 * Oxirgi `days` kun uchun foizlar qatori (eng eskisi birinchi).
 * O'lchanmagan kun — `null` (Sparkline uni UZILISH qilib chizadi, nol
 * qilib emas: nol "hech kim kelmadi" degani bo'lardi).
 */
export function trendValues(daily: readonly AnalyticsDaily[], endDate: string, days = 14): Array<number | null> {
  const byDate = new Map(daily.map((row) => [row.date, row.rate]));
  const out: Array<number | null> = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = addDays(endDate, -i);
    out.push(byDate.get(date) ?? null);
  }
  return out;
}

// ───────────────────────────────────────────── Bo'linmalar

export interface UnitRow {
  /** Ro'yxat kaliti (fakultetsizlarda `id` null bo'lishi mumkin). */
  key: string;
  id: string | null;
  name: string;
  type: 'xodim' | 'talaba';
  /** Bo'linma turi — "Kafedra", "Fakultet"… */
  kindLabel: string;
  rate: number | null;
  present: number;
  late: number;
  absent: number;
  total: number;
  notYet: number;
  noData: number;
  dayOff: number;
}

/** Kafedralar/bo'limlar → qatorlar. */
export function staffUnitRows(list: readonly KafedraStat[] | null | undefined, kindLabel: (unit: KafedraStat) => string): UnitRow[] {
  return (list ?? []).map((unit) => ({
    key: `xodim:${unit.id}`,
    id: unit.id,
    name: unit.name,
    type: 'xodim' as const,
    kindLabel: kindLabel(unit),
    rate: unit.rate,
    present: unit.present,
    late: unit.late,
    absent: unit.absent,
    total: unit.staffTotal,
    notYet: unit.notYet,
    noData: unit.noData,
    dayOff: unit.dayOff,
  }));
}

/** Fakultetlar → qatorlar. */
export function studentUnitRows(list: readonly FacultyCounts[] | null | undefined): UnitRow[] {
  return (list ?? []).map((faculty) => ({
    key: `talaba:${faculty.id ?? 'fakultetsiz'}`,
    id: faculty.id,
    name: faculty.name,
    type: 'talaba' as const,
    kindLabel: 'Fakultet',
    rate: faculty.rate,
    present: faculty.present,
    late: faculty.late,
    absent: faculty.absent,
    total: faculty.total,
    notYet: faculty.notYet,
    noData: faculty.noData,
    dayOff: faculty.dayOff,
  }));
}

/** Filtrga mos qatorlar (xodim / talaba / ikkalasi). */
export function rowsForScope(staff: UnitRow[], students: UnitRow[], scope: Scope): UnitRow[] {
  if (scope === 'xodim') return staff;
  if (scope === 'talaba') return students;
  return [...staff, ...students];
}

/**
 * Yomoni birinchi: avval o'lchangan va past foizli bo'linmalar, eng
 * oxirida umuman o'lchanmaganlari (`rate === null`) — ular "yomon" emas,
 * shunchaki ma'lumoti yo'q, shuning uchun ro'yxat boshini egallamaydi.
 */
export function worstFirst(rows: readonly UnitRow[]): UnitRow[] {
  return [...rows].sort((a, b) => {
    if (a.rate === null && b.rate === null) return a.name.localeCompare(b.name, 'uz');
    if (a.rate === null) return 1;
    if (b.rate === null) return -1;
    return a.rate - b.rate || b.total - a.total || a.name.localeCompare(b.name, 'uz');
  });
}

/** Qidiruv: apostrof turlari va katta-kichik harf farq qilmaydi. */
export function filterUnits(rows: readonly UnitRow[], query: string): UnitRow[] {
  const text = query.trim().toLowerCase().replace(/[‘’`ʻʼ]/g, "'");
  if (!text) return [...rows];
  return rows.filter((row) => row.name.toLowerCase().replace(/[‘’`ʻʼ]/g, "'").includes(text));
}

/** Foizni bir xil ko'rinishda chiqarish: "87%" yoki "—". */
export function pct(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : `${Math.round(value)}%`;
}
