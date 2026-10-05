import { buildQuery } from './apiClient';
import { isFixedPreset, resolvePreset, type FixedPreset } from './reportPeriods';
import { isMonth, monthOf, todayInTashkent } from './uzDate';

/** Hisobotlar sahifasi (`/api/hisobot/*`, camera-api/app/routers/hisobot.py).
 *  Xodimlar va talabalar — alohida: sonlar, filtrlar va mezonlar aralashmaydi. */

export type HisobotKind = 'talaba' | 'xodim';
export type HisobotSection = 'xodimlar' | 'talabalar';
export type HisobotTone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

export interface HisobotCriterion {
  key: string;
  /** Buyurtmachi ro'yxatidagi raqam (6, 7, 8, 9, 10, 15, 19, 21, 22). */
  code?: number | null;
  label: string;
  /** Bir qatorli tushuntirish: bu son nimani o'lchaydi (vaqtlar ish vaqti sozlamasidan). */
  description: string;
  indicator: string;
  tone: HisobotTone;
  /** Hozir hisoblab bo'lmasa — sababi oddiy tilda; aks holda null. */
  unavailable: string | null;
  available: boolean;
}

export interface HisobotTile {
  label: string;
  value: string | number;
  unit: string;
  hint: string | null;
  tone: HisobotTone;
}

export interface HisobotColumn {
  key: string;
  label: string;
  unit: string;
  /** Qaysi yo'nalish yaxshi: 'up' — katta yaxshi (davomat), 'down' — kichik yaxshi. */
  better: 'up' | 'down' | 'none';
  /** 'text' — matnli katak (holat, izoh), 'number' — raqam. */
  type?: 'text' | 'number';
}

export interface HisobotPerson {
  id: string;
  full_name: string;
  initials: string;
  photo_url: string | null;
  unit: string;
  values: Record<string, string | number | null>;
}

export interface HisobotBreakdownRow {
  id: string;
  name: string;
  value: number | null;
  detail: string | null;
  headcount: number | null;
}

export interface HisobotReport {
  kind: HisobotKind;
  period: { from: string; to: string; days: number };
  /** Tanlovning odamcha nomi: "Davolash ishi, 2-kurs, DI-2301 guruhi". */
  scope: string;
  population: { total: number; enrolled: number; not_enrolled: number };
  criteria: HisobotCriterion[];
  criterion: string;
  report: {
    /** Tepadagi javob: plitkalardagi ayni sonlardan tuzilgan 1–3 gap. */
    summary: string[];
    tiles: HisobotTile[];
    trend: {
      unit: '%' | 'ta';
      points: { date: string; value: number | null }[];
      title: string;
      axis: string;
      explain: string;
    };
    breakdown: {
      title: string;
      subtitle: string;
      unit: string;
      better: 'up' | 'down';
      rows: HisobotBreakdownRow[];
      /** false — qatorlar bo'linma emas (masalan binolar), ustiga bosib filtrlanmaydi. */
      drill?: boolean;
    } | null;
    columns: HisobotColumn[];
    people: HisobotPerson[];
    people_total: number;
    people_title: string;
    people_hint: string;
    /** Ro'yxat bo'sh bo'lsa — sababi va nima qilish kerakligi. */
    empty: { title: string; description: string } | null;
    /** Bu son hozir umuman hisoblanmayapti (modul o'chiq, jadval yo'q...). */
    blocked: boolean;
    sort_key: string | null;
    worst_desc: boolean;
    note: string | null;
  };
}

export interface HisobotFilterOptions {
  faculties: { id: string; name: string; count: number }[];
  groups: { faculty_id: string; course: number | null; name: string; count: number }[];
  courses: number[];
  units: { id: string; name: string; kind: string; count: number }[];
  unit_kinds: { id: string; label: string }[];
}

/** Sahifa ko'rinishlari: 'taxta' — holat taxtasi, 'royxat' — batafsil,
 *  'tabel' — oylik davomat varag'i (qog'ozga bosiladigan hujjat). */
/** Uch ko'rinish: holat taxtasi (rahbar uchun), ro'yxat (batafsil) va
 *  oylik tabel (imzolanadigan hujjat). Eski havolalardagi `tahlil`
 *  taxtaga tushadi. */
export type HisobotView = 'holat' | 'taxta' | 'royxat' | 'tabel' | 'kpi';

/** URL'dagi holat — havola bilan ulashiladi, "orqaga" ishlaydi. */
export interface HisobotState {
  section: HisobotSection;
  view: HisobotView;
  /** Oylik tabel uchun "YYYY-MM" (analitik ko'rinishda ishlatilmaydi). */
  month: string;
  preset: FixedPreset | 'custom';
  from: string;
  to: string;
  criterion: string;
  faculty: string;
  course: string;
  group: string;
  unitKind: string;
  unit: string;
  q: string;
}

function readView(raw: string | null): HisobotView {
  if (raw === 'tabel') return 'tabel';
  if (raw === 'royxat') return 'royxat';
  if (raw === 'kpi') return 'kpi';
  if (raw === 'holat') return 'holat';
  return 'taxta'; // 'tahlil' — eski nom, shu yerga tushadi
}

export const SECTION_KIND: Record<HisobotSection, HisobotKind> = { xodimlar: 'xodim', talabalar: 'talaba' };
export const PERIOD_PRESETS: readonly FixedPreset[] = ['today', 'week', 'month'];

/** Bo'lim almashganda tozalanadigan (bo'limga xos) parametrlar. */
const SECTION_PARAMS = ['mezon', 'fakultet', 'kurs', 'guruh', 'turi', 'bolinma', 'q'] as const;

export function readState(params: URLSearchParams, today: string = todayInTashkent()): HisobotState {
  const section: HisobotSection = params.get('bolim') === 'talabalar' ? 'talabalar' : 'xodimlar';
  const rawPreset = params.get('davr');
  let preset: HisobotState['preset'] = isFixedPreset(rawPreset) ? rawPreset : 'today';
  let range = resolvePreset(isFixedPreset(rawPreset) ? rawPreset : 'today', today);
  if (rawPreset === 'custom') {
    const from = params.get('dan');
    const to = params.get('gacha');
    if (from && to && /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to) && from <= to) {
      preset = 'custom';
      range = { from, to };
    }
  }
  return {
    section,
    view: readView(params.get('korinish')),
    month: isMonth(params.get('oy')) ? (params.get('oy') as string) : monthOf(today),
    preset,
    from: range.from,
    to: range.to,
    criterion: params.get('mezon') ?? '',
    faculty: section === 'talabalar' ? params.get('fakultet') ?? '' : '',
    course: section === 'talabalar' ? params.get('kurs') ?? '' : '',
    group: section === 'talabalar' ? params.get('guruh') ?? '' : '',
    unitKind: section === 'xodimlar' ? params.get('turi') ?? '' : '',
    unit: section === 'xodimlar' ? params.get('bolinma') ?? '' : '',
    q: params.get('q') ?? '',
  };
}

const PARAM_OF: Partial<Record<keyof HisobotState, string>> = {
  criterion: 'mezon',
  faculty: 'fakultet',
  course: 'kurs',
  group: 'guruh',
  unitKind: 'turi',
  unit: 'bolinma',
  q: 'q',
};

/** Holat o'zgarishini URL parametrlariga yozadi. Kaskad: yuqori filtr
 *  o'zgarsa, unga bog'liq pastkilari tozalanadi (fakultet -> kurs -> guruh,
 *  bo'linma turi -> bo'linma); bo'lim almashsa — bo'limga xos hammasi. */
export function writeState(current: URLSearchParams, patch: Partial<HisobotState>): URLSearchParams {
  const next = new URLSearchParams(current);
  const set = (key: string, value: string | undefined) => {
    if (value) next.set(key, value);
    else next.delete(key);
  };
  // Ko'rinish va oy bo'limga bog'liq emas: xodimdan talabaga o'tganda
  // ham odam o'sha oyning tabelida qoladi.
  // Standart ko'rinish (taxta) URL'ga yozilmaydi. Ilgari faqat 'tabel'
  // yozilardi — 'royxat' tanlansa ham URL'da qolmay, taxtaga qaytib ketardi.
  if (patch.view !== undefined) set('korinish', patch.view === 'taxta' ? undefined : patch.view);
  if (patch.month !== undefined) set('oy', patch.month);
  if (patch.section !== undefined) {
    if (patch.section !== (current.get('bolim') === 'talabalar' ? 'talabalar' : 'xodimlar')) {
      SECTION_PARAMS.forEach((key) => next.delete(key));
    }
    set('bolim', patch.section === 'xodimlar' ? undefined : patch.section);
  }
  if (patch.preset !== undefined) {
    set('davr', patch.preset === 'today' ? undefined : patch.preset);
    if (patch.preset === 'custom') {
      set('dan', patch.from);
      set('gacha', patch.to);
    } else {
      next.delete('dan');
      next.delete('gacha');
    }
  }
  if (patch.faculty !== undefined) {
    next.delete('kurs');
    next.delete('guruh');
  }
  if (patch.course !== undefined) next.delete('guruh');
  if (patch.unitKind !== undefined) next.delete('bolinma');
  for (const [field, param] of Object.entries(PARAM_OF) as [keyof HisobotState, string][]) {
    if (patch[field] !== undefined) set(param, String(patch[field]));
  }
  return next;
}

// Faol filtrlarni sanash endi FilterBar'da (src/ui/Toolbar.tsx) — bitta
// joyda, barcha sahifalarda bir xil. Bu yerdagi nusxa `q`ni trim qilmay
// sanardi: bitta probel "Tozalash (1)" chiqarib, hech nimani filtrlamasdi.

function queryParams(state: HisobotState, criterion?: string) {
  return {
    kind: SECTION_KIND[state.section],
    from: state.from,
    to: state.to,
    criterion: criterion ?? (state.criterion || undefined),
    faculty: state.faculty || undefined,
    course: state.course || undefined,
    group: state.group || undefined,
    unit_kind: state.unitKind || undefined,
    unit: state.unit || undefined,
    q: state.q.trim() || undefined,
  };
}

export const hisobotPaths = {
  filters: (kind: HisobotKind) => `/api/hisobot/filters${buildQuery({ kind })}`,
  report: (state: HisobotState) => `/api/hisobot/report${buildQuery(queryParams(state))}`,
  export: (state: HisobotState, criterion: string) =>
    `/api/hisobot/export.xlsx${buildQuery(queryParams(state, criterion))}`,
};

/** Kurs va guruh variantlari — tanlangan fakultet (va kurs) doirasida. */
export function courseOptions(options: HisobotFilterOptions | null, faculty: string): number[] {
  if (!options) return [];
  const courses = new Set<number>();
  for (const g of options.groups) {
    if (g.course !== null && (!faculty || g.faculty_id === faculty)) courses.add(g.course);
  }
  return [...courses].sort((a, b) => a - b);
}

export function groupOptions(options: HisobotFilterOptions | null, faculty: string, course: string): string[] {
  if (!options) return [];
  const names = new Set<string>();
  for (const g of options.groups) {
    if (faculty && g.faculty_id !== faculty) continue;
    if (course && String(g.course) !== course) continue;
    names.add(g.name);
  }
  return [...names].sort((a, b) => a.localeCompare(b, 'uz'));
}

export function unitOptions(options: HisobotFilterOptions | null, unitKind: string) {
  if (!options) return [];
  return options.units.filter((u) => !unitKind || u.kind === unitKind);
}

/** Jadval qiymati: "87%", "3 kun", "08:15", yoki "—". */
export function formatCell(value: string | number | null | undefined, unit: string): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  const text = Number.isInteger(value) ? String(value) : value.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
  if (unit === '%') return `${text}%`;
  return unit ? `${text} ${unit}` : text;
}

/**
 * Chop etilgan hujjatdagi rostgo'ylik izohi — jadvalning ustida turadi.
 *
 * Tepadagi ko'rsatkichlar BUTUN ro'yxat bo'yicha hisoblanadi, jadval esa
 * serverda chegaralangan (eng muhim qatorlar). Bu farq qog'ozda
 * ko'rinmasdi: o'quvchi jadvalni to'liq ro'yxat deb o'qib, sonlarni
 * o'zi qayta sanaganda ular to'g'ri kelmasdi. Endi hujjatning o'zi
 * nechta odam hisoblangani, nechta qator bosilgani va to'liq ro'yxatni
 * qayerdan olishni so'z bilan aytadi.
 *
 * @param population tepadagi ko'rsatkichlar qamragan odamlar soni
 * @param printed qog'ozga tushadigan qatorlar soni
 * @param total shu ro'yxatga mos keladigan jami odamlar soni
 */
export function printScopeNote(population: number, printed: number, total: number): string {
  const n = (value: number) => value.toLocaleString('ru-RU');
  const head = `Yuqoridagi ko'rsatkichlar ${n(population)} kishi bo'yicha hisoblangan.`;
  if (printed >= total) {
    return `${head} Quyidagi jadvalda shu holatga mos ${n(total)} ta qatorning hammasi chop etilgan.`;
  }
  return (
    `${head} Quyidagi jadvalda esa ${n(total)} ta qatordan faqat eng muhim ${n(printed)} tasi chop etilgan — ` +
    `qog'ozga minglab qator chiqarilmaydi. To'liq ro'yxat «Excel» tugmasi orqali yuklab olinadi.`
  );
}

/** Kesim qatorini bosish — bir pog'ona chuqurroq filtr (fakultet -> kurs
 *  -> guruh; xodimda — bo'linma). Pastroq pog'ona bo'lmasa null. */
export function drillPatch(state: HisobotState, rowId: string): Partial<HisobotState> | null {
  if (state.section === 'xodimlar') return state.unit ? null : { unit: rowId };
  if (!state.faculty) return { faculty: rowId };
  if (!state.course && !state.group) return rowId && rowId !== '0' ? { course: rowId } : null;
  if (!state.group) return rowId ? { group: rowId } : null;
  return null;
}

/* ------------------------------------------------------------------
 * Hujjat raqami (ro'yxat kodi).
 *
 * Har bir hisobot — rasmiy hujjat, demak o'z raqami bo'lishi kerak:
 * qog'ozdagi varaqni ekrandagi ko'rinish bilan solishtirish, kelishuv
 * xatida "FERMI/TBL/2026-09/XDM-0007" deb yozish mumkin bo'lsin.
 *
 * Shakl: TASHKILOT / HUJJAT TURI / DAVR / BO'LIM-TARTIB
 *   FERMI/TBL/2026-09/XDM-0001
 *
 * Raqam HOLATDAN kelib chiqadi va tasodifiy emas: bir xil tanlov —
 * doim bir xil kod. Shuning uchun tartib raqami sanagichdan emas,
 * tanlovning o'zidan (FNV-1a) hisoblanadi; filtrsiz to'liq hujjat
 * doim «0001» bo'ladi.
 * ------------------------------------------------------------------ */

/** Tashkilot kodi — boshqa muassasaga o'rnatishda almashtiriladi. */
export const DOCUMENT_ORG_CODE = 'FERMI';

const DOCUMENT_VIEW_CODE: Record<HisobotView, string> = { tabel: 'TBL', taxta: 'HLT', royxat: 'RYX', kpi: 'KPI', holat: 'JHL' };
const DOCUMENT_SECTION_CODE: Record<HisobotSection, string> = { xodimlar: 'XDM', talabalar: 'TLB' };

/** Tanlovdan deterministik 4 xonali tartib raqami (0002–9999).
 *  Tanlov bo'sh bo'lsa — 0001 (butun bo'lim bo'yicha asosiy hujjat). */
function referenceSerial(parts: readonly (string | null | undefined)[]): string {
  const key = parts
    .map((part) => (part ?? '').trim())
    .filter(Boolean)
    .join('|');
  if (!key) return '0001';
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return String((hash % 9998) + 2).padStart(4, '0');
}

/** Davr bo'lagi: tabelda "2026-09", tahlilda "20260901-20260919". */
function referencePeriod(view: HisobotView, state: Pick<HisobotState, 'month' | 'from' | 'to'>): string {
  if (view === 'tabel') return state.month;
  const compact = (iso: string) => iso.replace(/-/g, '');
  return `${compact(state.from)}-${compact(state.to)}`;
}

/** Hujjat raqamini bo'laklardan tuzadi (TabelView o'z holatini bilmaydi,
 *  shuning uchun quruq ma'lumotdan ham kod chiqara olishi kerak). */
export function buildReference(input: {
  view: HisobotView;
  section: HisobotSection;
  /** Tayyor davr bo'lagi: "2026-09" yoki "20260901-20260919". */
  period: string;
  /** Tartib raqamiga ta'sir qiladigan tanlov bo'laklari. */
  parts?: readonly (string | null | undefined)[];
  org?: string;
}): string {
  const org = (input.org ?? DOCUMENT_ORG_CODE).toUpperCase();
  const serial = referenceSerial(input.parts ?? []);
  return `${org}/${DOCUMENT_VIEW_CODE[input.view]}/${input.period}/${DOCUMENT_SECTION_CODE[input.section]}-${serial}`;
}

/** Joriy holat uchun hujjat raqami — sahifa shuni ishlatadi. */
export function documentReference(state: HisobotState, org: string = DOCUMENT_ORG_CODE): string {
  const parts =
    state.view === 'tabel'
      ? [state.faculty, state.course, state.group, state.unitKind, state.unit, state.q.trim()]
      : [state.criterion, state.faculty, state.course, state.group, state.unitKind, state.unit, state.q.trim()];
  return buildReference({
    view: state.view,
    section: state.section,
    period: referencePeriod(state.view, state),
    parts,
    org,
  });
}
