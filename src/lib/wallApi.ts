/** Situatsion markaz devor ekrani (/markaz-ekran) — API o'ramlari va sof
 *  yordamchilar (joylashuv, aylanish, konfiguratsiya). Yordamchilar
 *  wallApi.test.ts da tekshiriladi. */
import { api, buildQuery, type CallOptions } from './apiClient';
import type { Counts, LastArrival } from './situationApi';

// ───────────────────────────────────────────── Turlar (SITUATION_API.md §13, §14, §17)

export interface EnrollCounts {
  total: number;
  confirmed: number;
  pending: number;
  none: number;
  pct: number | null;
}

export interface WallEnrollment {
  students: EnrollCounts;
  staff: EnrollCounts;
  byFaculty: Array<EnrollCounts & { id: string | null; name: string }>;
  studentsDataAvailable: boolean;
}

export interface WallUnit {
  id: string;
  name: string;
  kind: string;
  total: number;
  present: number;
  rate: number | null;
}

export interface WallHighEvent {
  id: string;
  moduleName: string;
  cameraName: string;
  building: string;
  time: string;
  status: string;
  /** Faqat jonli (websocket) yoki /api/events orqali to'ldirilganda. */
  snapshotUrl?: string | null;
}

export type SpotlightKind = 'unit' | 'group';

export interface SpotlightItem {
  kind: SpotlightKind;
  id: string;
  name: string;
  rate: number | null;
}

export interface Wall {
  date: string;
  generatedAt: string;
  students: Counts;
  staff: Counts;
  studentsDataAvailable: boolean;
  topUnits: WallUnit[];
  bottomUnits: WallUnit[];
  lastArrivals: LastArrival[];
  highEvents: WallHighEvent[];
  camerasOnline: number;
  /** Faol (ishlashi kerak bo'lgan) kameralar — "nofaol"lari kirmaydi. */
  camerasTotal: number;
  /** Ochiq "yuqori" hodisalarning to'liq soni (`highEvents` — faqat 5 tasi). */
  highOpen?: number;
  enrollment: WallEnrollment;
  spotlight: SpotlightItem[];
}

export interface ChronicRow {
  id: string;
  fullName: string;
  unitId: string;
  unit: string;
  absentDays: number;
  lateDays: number;
}

/** Spotlight panelidagi bitta yuz (bo'linma xodimi yoki guruh talabasi). */
export interface SpotlightFace {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  status: string;
  checkIn: string | null;
  /** Yuzi ro'yxatdan o'tmagan — kameralar tanimaydi ("kelmadi" emas). */
  noFace?: boolean;
}

export interface SpotlightDetail {
  key: string;
  kind: SpotlightKind;
  name: string;
  subtitle: string;
  counts: Counts;
  faces: SpotlightFace[];
}

// ───────────────────────────────────────────── So'rovlar

const BASE = '/api/situation';

export function getWall(opts?: CallOptions): Promise<Wall> {
  return api.get<Wall>(`${BASE}/wall`, undefined, opts);
}

export function getChronic(from: string, to: string, opts?: CallOptions): Promise<ChronicRow[]> {
  return api.get<ChronicRow[]>(`${BASE}/analytics/chronic${buildQuery({ from, to, type: 'xodim' })}`, undefined, opts);
}

interface RawFace {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  status: string;
  checkIn: string | null;
  biometricsStatus?: string;
}

interface RawKafedra {
  name: string;
  kind: string;
  today: Counts;
  teachers: RawFace[];
}

interface RawGroup {
  group: { name: string; faculty: string | null; course: number | null; totals: Counts };
  students: RawFace[];
}

const UNIT_KIND_LABEL: Record<string, string> = {
  kafedra: 'Kafedra',
  dekanat: 'Dekanat',
  bolim: "Bo'lim",
  lavozim: 'Lavozim',
};

function pickFace(f: RawFace): SpotlightFace {
  return {
    id: f.id,
    fullName: f.fullName,
    photoUrl: f.photoUrl,
    initials: f.initials,
    status: f.status,
    checkIn: f.checkIn,
    noFace: f.biometricsStatus !== undefined && f.biometricsStatus !== 'tasdiqlangan',
  };
}

export async function getSpotlightDetail(item: SpotlightItem, opts?: CallOptions): Promise<SpotlightDetail> {
  const key = spotlightKey(item);
  if (item.kind === 'unit') {
    const d = await api.get<RawKafedra>(`${BASE}/kafedras/${encodeURIComponent(item.id)}`, undefined, opts);
    return {
      key,
      kind: 'unit',
      name: d.name,
      subtitle: `${UNIT_KIND_LABEL[d.kind] ?? "Bo'linma"} · xodimlar`,
      counts: d.today,
      faces: sortFaces(d.teachers.map(pickFace)),
    };
  }
  const d = await api.get<RawGroup>(`${BASE}/groups/${encodeURIComponent(item.id)}`, undefined, opts);
  const parts = [d.group.faculty, d.group.course ? `${d.group.course}-kurs` : null].filter(Boolean);
  return {
    key,
    kind: 'group',
    name: d.group.name,
    subtitle: parts.length ? `Guruh · ${parts.join(' · ')}` : 'Guruh',
    counts: d.group.totals,
    faces: sortFaces(d.students.map(pickFace)),
  };
}

// ───────────────────────────────────────────── Sof yordamchilar

export const WALL_PANELS = ['A', 'B', 'C', 'D', 'E', 'F'] as const;
export type WallPanelId = (typeof WALL_PANELS)[number];

export const PANEL_TITLES: Record<WallPanelId, string> = {
  A: 'Bugun',
  B: 'Jonli kelish',
  C: 'Diqqat markazida',
  D: 'Reyting',
  E: 'Xavfsizlik',
  F: 'Kameralar',
};

export const DEFAULT_PANELS: WallPanelId[] = ['A', 'B', 'C', 'D', 'E'];
export const DEFAULT_ROTATE_S = 15;

export interface WallConfig {
  panels: WallPanelId[];
  rotate: number;
  cameras: string[];
}

/** `?panels=A,B,C&rotate=15&cameras=id1,id2` → konfiguratsiya. Noma'lum
 *  qiymatlar tashlab yuboriladi; bo'sh ro'yxat → standart panellar. */
export function parseWallConfig(search: string | URLSearchParams): WallConfig {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search;
  const rawPanels = (params.get('panels') ?? '')
    .toUpperCase()
    .split(',')
    .map((s) => s.trim())
    .filter((s): s is WallPanelId => (WALL_PANELS as readonly string[]).includes(s));
  const panels = WALL_PANELS.filter((p) => rawPanels.includes(p));
  const rotateNum = Number(params.get('rotate'));
  const rotate = Number.isFinite(rotateNum) && rotateNum > 0 ? Math.min(300, Math.max(5, Math.round(rotateNum))) : DEFAULT_ROTATE_S;
  const cameras = (params.get('cameras') ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 4);
  return { panels: panels.length ? panels : [...DEFAULT_PANELS], rotate, cameras };
}

/** Konfiguratsiya → query satri (standart qiymatlar yozilmaydi). */
export function buildWallQuery(cfg: WallConfig): string {
  const params = new URLSearchParams();
  const panels = WALL_PANELS.filter((p) => cfg.panels.includes(p));
  if (panels.join(',') !== DEFAULT_PANELS.join(',')) params.set('panels', panels.join(','));
  if (cfg.rotate !== DEFAULT_ROTATE_S) params.set('rotate', String(cfg.rotate));
  if (cfg.cameras.length) params.set('cameras', cfg.cameras.slice(0, 4).join(','));
  const qs = params.toString();
  return qs ? `?${qs.replace(/%2C/g, ',')}` : '';
}

export interface WallLayout {
  columns: string;
  rows: string;
  areas: string;
}

/** Panel kengligi og'irliklari (ultra keng ekranda bitta qatorda). */
const WIDE_WEIGHT: Record<WallPanelId, number> = { A: 1.15, B: 1.1, C: 2, D: 1.1, E: 1, F: 1.5 };

/**
 * Panellar joylashuvi. Nisbat (en/bo'y) ≥ 2.6 — ultra keng LED devor
 * (3840×1080, 5760×1080): hamma panel bitta qatorda. Aks holda (16:9):
 * ikki qator; "C" (spotlight) bo'yiga to'liq ustun, qolganlari ustun
 * bo'yicha juft-juft ([A/D], [B/E], [F]); toq qolgani to'liq bo'y oladi.
 */
export function computeWallLayout(panels: readonly WallPanelId[], aspect: number): WallLayout {
  const list = WALL_PANELS.filter((p) => panels.includes(p));
  if (list.length === 0) return { columns: '1fr', rows: '1fr', areas: '"."' };
  if (aspect >= 2.6 || list.length <= 2) {
    return {
      columns: list.map((p) => `${WIDE_WEIGHT[p]}fr`).join(' '),
      rows: '1fr',
      areas: `"${list.join(' ')}"`,
    };
  }
  const order: WallPanelId[] = (['A', 'D', 'B', 'E', 'F'] as WallPanelId[]).filter((p) => list.includes(p));
  const cols: Array<[WallPanelId, WallPanelId]> = [];
  for (let i = 0; i < order.length; i += 2) {
    const top = order[i];
    const bottom = order[i + 1] ?? top;
    cols.push([top, bottom]);
  }
  if (list.includes('C')) cols.splice(Math.min(1, cols.length), 0, ['C', 'C']);
  const weight = (col: [WallPanelId, WallPanelId]) => (col[0] === 'C' ? 1.5 : col[0] === 'F' ? 1.2 : 1);
  return {
    columns: cols.map((c) => `${weight(c)}fr`).join(' '),
    rows: '1fr 1fr',
    areas: `"${cols.map((c) => c[0]).join(' ')}" "${cols.map((c) => c[1]).join(' ')}"`,
  };
}

/** Aylanuvchi indeks (ro'yxat qisqarsa ham chegaradan chiqmaydi). */
export function nextRotationIndex(current: number, length: number): number {
  if (length <= 0) return 0;
  return (((current + 1) % length) + length) % length;
}

export function spotlightKey(item: Pick<SpotlightItem, 'kind' | 'id'>): string {
  return `${item.kind}:${item.id}`;
}

/** Yangi spotlight ro'yxatida joriy elementning o'rni saqlanadi; u yo'q
 *  bo'lsa — shu indeksdan davom etadi. */
export function reconcileRotation(prevKey: string | null, prevIndex: number, items: readonly SpotlightItem[]): number {
  if (items.length === 0) return 0;
  if (prevKey) {
    const found = items.findIndex((it) => spotlightKey(it) === prevKey);
    if (found >= 0) return found;
  }
  return Math.min(Math.max(0, prevIndex), items.length - 1);
}

/**
 * Yuzlar setkasi: `n` ta kartani `width × height` maydonga eng katta
 * o'lchamda joylaydigan ustunlar soni. Karta nisbati en/bo'y = `tileAspect`
 * (rasm + ism). `gap` — kartalar orasidagi masofa (px).
 */
export function fitGrid(n: number, width: number, height: number, tileAspect = 0.78, gap = 8): { cols: number; rows: number; tile: number } {
  if (n <= 0 || width <= 0 || height <= 0) return { cols: 1, rows: 1, tile: 0 };
  let best = { cols: 1, rows: n, tile: 0 };
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const w = (width - gap * (cols - 1)) / cols;
    const h = (height - gap * (rows - 1)) / rows;
    const tileW = Math.min(w, h * tileAspect);
    if (tileW > best.tile) best = { cols, rows, tile: Math.floor(tileW) };
  }
  return best;
}

const STATUS_ORDER: Record<string, number> = { keldi: 0, kech_keldi: 1, kutilmoqda: 2, kelmadi: 3, dam_olish: 4, malumot_yoq: 5 };

/** Kelganlar oldinda (kelish vaqti bo'yicha), keyin kutilayotganlar va h.k. */
export function sortFaces<T extends { status: string; checkIn: string | null; fullName: string }>(faces: readonly T[]): T[] {
  return [...faces].sort((a, b) => {
    const sa = STATUS_ORDER[a.status] ?? 9;
    const sb = STATUS_ORDER[b.status] ?? 9;
    if (sa !== sb) return sa - sb;
    if (a.checkIn && b.checkIn && a.checkIn !== b.checkIn) return a.checkIn < b.checkIn ? -1 : 1;
    return a.fullName.localeCompare(b.fullName);
  });
}

/** Jonli kelishni ro'yxat boshiga qo'shadi (takror odam bo'lsa ko'chiradi). */
export function mergeArrival<T extends { id: string }>(list: readonly T[], item: T, limit = 12): T[] {
  return [item, ...list.filter((x) => x.id !== item.id)].slice(0, limit);
}

/** Vaqtni "HH:MM" ga keltiradi. Jonli yozuvlar `hhmm()` dan ("08:12"),
 *  server yozuvlari esa to'liq ISO ("2026-09-20T08:12:03") bo'lishi mumkin —
 *  ularni satr sifatida to'g'ridan-to'g'ri solishtirish barcha jonli
 *  kelishlarni yo'qotib yuborardi ("08:12" < "2026-..."). */
function hhmmOf(time: string): string {
  const m = /(\d{2}):(\d{2})/.exec(time);
  return m ? `${m[1]}:${m[2]}` : time;
}

/** Poll natijasini jonli qo'shilganlar bilan birlashtiradi: server hali
 *  ko'rmagan (keshdagi) yangi kelishlar yo'qolib qolmasin. */
export function mergeArrivalLists<T extends { id: string; time: string }>(server: readonly T[], live: readonly T[], limit = 12): T[] {
  const seen = new Set(server.map((a) => a.id));
  const head = server[0] ? hhmmOf(server[0].time) : null;
  const extra = live.filter((a) => !seen.has(a.id) && (head === null || hhmmOf(a.time) >= head));
  return [...extra, ...server].slice(0, limit);
}

/** Ekran kuyishidan himoya: 2 px radiusdagi sekin aylanma siljish. */
const BURN_PATH: ReadonlyArray<[number, number]> = [
  [0, 0], [1, 0], [2, 1], [1, 2], [0, 1], [-1, 0], [-2, -1], [-1, -2], [0, -1],
];
export function burnInOffset(step: number): [number, number] {
  const i = ((Math.floor(step) % BURN_PATH.length) + BURN_PATH.length) % BURN_PATH.length;
  return BURN_PATH[i];
}

/** "YYYY-MM-DD" dan `days` kun oldingi sana. */
export function shiftIsoDate(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}
