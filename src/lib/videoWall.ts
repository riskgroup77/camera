/**
 * Videodevor (src/pages/admin/VideoWallPage.tsx) — sof mantiq: setka
 * geometriyasi, kataklarni to'ldirish, sahifalash, aylanish (tur)
 * ketma-ketligi, qaysi katak jonli o'ynashi va saqlangan ko'rinishlarni
 * (JSON) tekshirish. React'ga bog'liq emas — vitest bilan tekshiriladi.
 */

export type WallLayout = '1x1' | '2x2' | '3x3' | '4x4' | '5x5' | '1+5' | '1+7';

export const WALL_LAYOUTS: WallLayout[] = ['1x1', '2x2', '3x3', '4x4', '5x5', '1+5', '1+7'];

export const LAYOUT_LABELS: Record<WallLayout, string> = {
  '1x1': '1',
  '2x2': '4',
  '3x3': '9',
  '4x4': '16',
  '5x5': '25',
  '1+5': '1+5',
  '1+7': '1+7',
};

/** Bitta katakning setkadagi joyi (0 dan boshlanadi). */
export interface WallCell {
  index: number;
  col: number;
  row: number;
  colSpan: number;
  rowSpan: number;
}

export interface WallGeometry {
  cols: number;
  rows: number;
  cells: WallCell[];
}

/** Katak: kamera id yoki bo'sh (null). */
export type WallTiles = (string | null)[];

/** Devorga kamera qo'yish so'rovi — `?kamera=<id>` havolasidan.
 *
 * `nonce` HAR bir yangi havola uchun ortadi. Parametr o'qilgandan keyin
 * URL'dan o'chiriladi, shuning uchun bir xil kamera qayta so'ralishi
 * mumkin: id yetarli emas, aynan shu son "bu boshqa so'rov" deyishga
 * imkon beradi. */
export interface WallCameraRequest {
  id: string;
  nonce: number;
}

function squareGrid(n: number): WallGeometry {
  const cells: WallCell[] = [];
  for (let row = 0; row < n; row += 1) {
    for (let col = 0; col < n; col += 1) {
      cells.push({ index: cells.length, col, row, colSpan: 1, rowSpan: 1 });
    }
  }
  return { cols: n, rows: n, cells };
}

/** Bitta katta (big x big) katak chap-yuqorida, qolganlari o'ng ustun va
 * pastki qatorda: 1+5 — 3x3 setka (katta 2x2), 1+7 — 4x4 setka (katta 3x3). */
function featuredGrid(size: number): WallGeometry {
  const big = size - 1;
  const cells: WallCell[] = [{ index: 0, col: 0, row: 0, colSpan: big, rowSpan: big }];
  for (let row = 0; row < big; row += 1) {
    cells.push({ index: cells.length, col: big, row, colSpan: 1, rowSpan: 1 });
  }
  for (let col = 0; col < size; col += 1) {
    cells.push({ index: cells.length, col, row: big, colSpan: 1, rowSpan: 1 });
  }
  return { cols: size, rows: size, cells };
}

export function layoutGeometry(layout: WallLayout): WallGeometry {
  switch (layout) {
    case '1x1':
      return squareGrid(1);
    case '2x2':
      return squareGrid(2);
    case '3x3':
      return squareGrid(3);
    case '4x4':
      return squareGrid(4);
    case '5x5':
      return squareGrid(5);
    case '1+5':
      return featuredGrid(3);
    case '1+7':
      return featuredGrid(4);
  }
}

export function layoutCapacity(layout: WallLayout): number {
  return layoutGeometry(layout).cells.length;
}

/** 1+N setkalarda katta katak (0) — jonli oqim unga birinchi beriladi. */
export function isFeaturedLayout(layout: WallLayout): boolean {
  return layout === '1+5' || layout === '1+7';
}

export function isWallLayout(value: unknown): value is WallLayout {
  return typeof value === 'string' && (WALL_LAYOUTS as string[]).includes(value);
}

/** Klaviatura: 1-5 — kvadrat setkalar, 6 — 1+5, 7 — 1+7. */
export function layoutForKey(key: string): WallLayout | null {
  const map: Record<string, WallLayout> = {
    '1': '1x1',
    '2': '2x2',
    '3': '3x3',
    '4': '4x4',
    '5': '5x5',
    '6': '1+5',
    '7': '1+7',
  };
  return map[key] ?? null;
}

// ---------------------------------------------------------------------------
// Kataklar bilan ishlash (hammasi yangi massiv qaytaradi)
// ---------------------------------------------------------------------------

export function emptyTiles(capacity: number): WallTiles {
  return Array.from({ length: capacity }, () => null);
}

/** Setka o'zgarganda kataklarni moslash.
 *
 * Kattalashganda — oxiriga bo'sh kataklar qo'shiladi (joylar saqlanadi).
 * Kichrayganda — agar barcha kameralar yangi sig'imga o'z joyida sig'sa,
 * joylari o'zgarmaydi; aks holda kameralar tartibi saqlangan holda
 * boshiga zichlanadi, sig'magan oxirgilari tushib qoladi. */
export function resizeTiles(tiles: WallTiles, capacity: number): WallTiles {
  if (tiles.length <= capacity) {
    return [...tiles, ...emptyTiles(capacity - tiles.length)];
  }
  const overflow = tiles.slice(capacity).some((id) => id !== null);
  if (!overflow) return tiles.slice(0, capacity);
  const ids = tiles.filter((id): id is string => id !== null).slice(0, capacity);
  return [...ids, ...emptyTiles(capacity - ids.length)];
}

/** Kamerani katakka qo'yish. Kamera devorda allaqachon boshqa katakda
 * bo'lsa — ikki katak almashadi (bitta kamera ikki marta ko'rinmaydi,
 * bu ikki HLS oqimi degani). */
export function placeCamera(tiles: WallTiles, index: number, cameraId: string): WallTiles {
  if (index < 0 || index >= tiles.length) return tiles;
  const next = [...tiles];
  const existing = next.indexOf(cameraId);
  if (existing === index) return tiles;
  if (existing !== -1) next[existing] = next[index];
  next[index] = cameraId;
  return next;
}

/** Birinchi bo'sh katakka qo'shadi. Kamera allaqachon devorda bo'lsa —
 * o'zgarishsiz, o'sha katak indeksi qaytadi. Bo'sh katak yo'q — null. */
export function addToFirstEmpty(tiles: WallTiles, cameraId: string): { tiles: WallTiles; index: number } | null {
  const existing = tiles.indexOf(cameraId);
  if (existing !== -1) return { tiles, index: existing };
  const empty = tiles.indexOf(null);
  if (empty === -1) return null;
  const next = [...tiles];
  next[empty] = cameraId;
  return { tiles: next, index: empty };
}

export function removeAt(tiles: WallTiles, index: number): WallTiles {
  if (index < 0 || index >= tiles.length || tiles[index] === null) return tiles;
  const next = [...tiles];
  next[index] = null;
  return next;
}

export function swapTiles(tiles: WallTiles, from: number, to: number): WallTiles {
  if (from === to || from < 0 || to < 0 || from >= tiles.length || to >= tiles.length) return tiles;
  const next = [...tiles];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** O'chirilgan (endi ro'yxatda yo'q) kameralarni kataklardan olib tashlash. */
export function pruneTiles(tiles: WallTiles, known: ReadonlySet<string>): WallTiles {
  if (tiles.every((id) => id === null || known.has(id))) return tiles;
  return tiles.map((id) => (id !== null && known.has(id) ? id : null));
}

/** Kataklarni faqat ISHONCHLI ro'yxat asosida tozalaydi.
 *
 * `known === null` — ro'yxat hali kelmagan yoki so'rov xato bergan;
 * bo'sh to'plam — server bo'sh javob qaytargan. Ikkalasi ham "barcha
 * kamera o'chirilgan" degani EMAS, shuning uchun bunday paytda kataklar
 * tegilmaydi: operator yig'gan devor bitta tarmoq uzilishidan yoki
 * server nosozligidan bo'shab qolmasligi kerak. */
export function pruneTilesIfKnown(tiles: WallTiles, known: ReadonlySet<string> | null): WallTiles {
  if (!known || known.size === 0) return tiles;
  return pruneTiles(tiles, known);
}

/** Xuddi shu qoida kamera identifikatorlari ro'yxati uchun (situatsion
 * markaz ekranining `?cameras=` sozlamasi). O'zgarish bo'lmasa — o'sha
 * massivning o'zi qaytadi. */
export function pruneCameraIds(ids: readonly string[], known: ReadonlySet<string> | null): readonly string[] {
  if (!known || known.size === 0) return ids;
  if (ids.every((id) => known.has(id))) return ids;
  return ids.filter((id) => known.has(id));
}

// ---------------------------------------------------------------------------
// Sahifalash ("ro'yxat bo'yicha" rejim: filtrlangan kameralar sahifama-sahifa)
// ---------------------------------------------------------------------------

export function pageCount(total: number, capacity: number): number {
  if (capacity <= 0) return 1;
  return Math.max(1, Math.ceil(total / capacity));
}

/** Sahifa raqamini (0 dan) chegaraga keltiradi; oxiridan keyin — boshiga
 * qaytmaydi (buni stepPage qiladi). */
export function clampPage(page: number, total: number, capacity: number): number {
  const pages = pageCount(total, capacity);
  if (!Number.isFinite(page)) return 0;
  return Math.min(Math.max(0, Math.trunc(page)), pages - 1);
}

/** Keyingi/oldingi sahifa — aylanma (oxirgidan keyin birinchi). */
export function stepPage(page: number, delta: number, total: number, capacity: number): number {
  const pages = pageCount(total, capacity);
  return (((clampPage(page, total, capacity) + delta) % pages) + pages) % pages;
}

export function pageTiles(ids: readonly string[], capacity: number, page: number): WallTiles {
  const start = clampPage(page, ids.length, capacity) * capacity;
  const slice = ids.slice(start, start + capacity);
  return [...slice, ...emptyTiles(capacity - slice.length)];
}

// ---------------------------------------------------------------------------
// Aylanish (tur) rejimi
// ---------------------------------------------------------------------------

export type TourKind = 'views' | 'pages';

export const TOUR_MIN_SECONDS = 5;
export const TOUR_MAX_SECONDS = 600;
export const TOUR_DEFAULT_SECONDS = 20;

export function normalizeTourInterval(seconds: unknown): number {
  const value = typeof seconds === 'number' ? seconds : Number(seconds);
  if (!Number.isFinite(value)) return TOUR_DEFAULT_SECONDS;
  return Math.min(TOUR_MAX_SECONDS, Math.max(TOUR_MIN_SECONDS, Math.round(value)));
}

/** Ko'rinishlar turi: joriy ko'rinishdan keyingisi (aylanma). Joriy
 * ko'rinish ro'yxatda bo'lmasa — birinchisi. Ro'yxat bo'sh — null. */
export function nextTourView(viewIds: readonly string[], currentId: string | null): string | null {
  if (viewIds.length === 0) return null;
  const index = currentId === null ? -1 : viewIds.indexOf(currentId);
  return viewIds[(index + 1) % viewIds.length];
}

/** Turda qatnashadigan ko'rinishlar: tanlanganlar (mavjud bo'lganlari,
 * saqlangan tartibda); hech biri tanlanmagan bo'lsa — hammasi. */
export function tourSequence(views: readonly WallView[], selectedIds: readonly string[]): string[] {
  const selected = new Set(selectedIds);
  const chosen = views.filter((view) => selected.has(view.id)).map((view) => view.id);
  return chosen.length > 0 ? chosen : views.map((view) => view.id);
}

// ---------------------------------------------------------------------------
// Qaysi katak jonli o'ynaydi
// ---------------------------------------------------------------------------

/** Bir vaqtda o'ynaydigan HLS pleyerlar chegarasi. Har pleyer — brauzerda
 * dekoder va MediaMTX'da o'quvchi; 25 katakli devorda hammasini jonli
 * ochish kuchsiz kompyuterni ham, serverni ham bo'g'ib qo'yadi. Chegaradan
 * tashqaridagi kataklar davriy yangilanadigan kadr (rasm) ko'rsatadi. */
export const WALL_MAX_LIVE = 16;

export type TilePlayback = 'live' | 'snapshot' | 'offline' | 'empty' | 'hidden';

export interface PlaybackInput {
  tiles: WallTiles;
  /** Kamera jonli (status==='live') va video manzili bormi. */
  isPlayable: (cameraId: string) => boolean;
  /** Bitta katak kattalashtirilgan — faqat u ko'rsatiladi. */
  maximized: number | null;
  /** 1+N setkada katta katak (0) ustuvor. */
  featured: boolean;
  maxLive?: number;
  /** Varaq fonda — hech narsa o'ynamaydi. */
  paused?: boolean;
}

export function planPlayback({
  tiles,
  isPlayable,
  maximized,
  featured,
  maxLive = WALL_MAX_LIVE,
  paused = false,
}: PlaybackInput): TilePlayback[] {
  const plan: TilePlayback[] = tiles.map((id) => (id === null ? 'empty' : isPlayable(id) ? 'snapshot' : 'offline'));
  if (maximized !== null && maximized >= 0 && maximized < tiles.length) {
    return plan.map((state, index) => {
      if (index !== maximized) return 'hidden';
      return state === 'snapshot' && !paused ? 'live' : state;
    });
  }
  if (paused) return plan;
  const order = tiles.map((_, index) => index);
  if (featured) order.sort((a, b) => (a === 0 ? -1 : b === 0 ? 1 : a - b));
  let live = 0;
  for (const index of order) {
    if (live >= maxLive) break;
    if (plan[index] === 'snapshot') {
      plan[index] = 'live';
      live += 1;
    }
  }
  return plan;
}

// ---------------------------------------------------------------------------
// Saqlangan ko'rinishlar ("Ko'rinishlar") va JSON eksport/import
// ---------------------------------------------------------------------------

export interface WallView {
  id: string;
  name: string;
  layout: WallLayout;
  tiles: WallTiles;
  updatedAt: string;
}

export const MAX_VIEWS = 100;
export const MAX_VIEW_NAME = 60;
export const VIEWS_EXPORT_KIND = 'situatsion-markaz/videodevor';
export const VIEWS_EXPORT_VERSION = 1;

export function newViewId(): string {
  const cryptoApi = globalThis.crypto as Crypto | undefined;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  return `v-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** Bitta ko'rinishni tekshirib, toza nusxasini qaytaradi; yaroqsiz — null.
 * Kataklar setka sig'imiga moslanadi, kamera id'lari satr bo'lishi shart,
 * takrorlangan kamera ikkinchi marta bo'sh katakka aylanadi. */
export function sanitizeView(raw: unknown): WallView | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.id !== 'string' || !ID_RE.test(value.id)) return null;
  if (typeof value.name !== 'string') return null;
  const name = value.name.trim().slice(0, MAX_VIEW_NAME);
  if (!name) return null;
  if (!isWallLayout(value.layout)) return null;
  if (!Array.isArray(value.tiles)) return null;
  const capacity = layoutCapacity(value.layout);
  const seen = new Set<string>();
  const tiles: WallTiles = value.tiles.slice(0, capacity).map((item) => {
    if (typeof item !== 'string' || !item || item.length > 64 || seen.has(item)) return null;
    seen.add(item);
    return item;
  });
  const updatedAt =
    typeof value.updatedAt === 'string' && !Number.isNaN(Date.parse(value.updatedAt))
      ? value.updatedAt
      : new Date(0).toISOString();
  return { id: value.id, name, layout: value.layout, tiles: resizeTiles(tiles, capacity), updatedAt };
}

/** localStorage'dan o'qilgan qiymat — yaroqsizlari jimgina tashlanadi,
 * takrorlangan id'ning birinchisi qoladi. */
export function sanitizeViews(raw: unknown): WallView[] {
  if (!Array.isArray(raw)) return [];
  const ids = new Set<string>();
  const views: WallView[] = [];
  for (const item of raw) {
    const view = sanitizeView(item);
    if (!view || ids.has(view.id)) continue;
    ids.add(view.id);
    views.push(view);
    if (views.length >= MAX_VIEWS) break;
  }
  return views;
}

export function serializeViews(views: readonly WallView[], now: Date = new Date()): string {
  return JSON.stringify(
    {
      kind: VIEWS_EXPORT_KIND,
      version: VIEWS_EXPORT_VERSION,
      exportedAt: now.toISOString(),
      views: views.map(({ id, name, layout, tiles, updatedAt }) => ({ id, name, layout, tiles, updatedAt })),
    },
    null,
    2,
  );
}

export interface ViewsImportResult {
  views: WallView[];
  /** Tashlab yuborilgan (yaroqsiz) yozuvlar soni. */
  skipped: number;
  error: string | null;
}

/** Eksport faylini o'qish. Faqat o'zimizning formatimiz (kind/version)
 * yoki ko'rinishlar massivi qabul qilinadi. */
export function parseViewsImport(text: string): ViewsImportResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { views: [], skipped: 0, error: "Fayl JSON formatida emas" };
  }
  let items: unknown;
  if (Array.isArray(data)) {
    items = data;
  } else if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>;
    if (record.kind !== VIEWS_EXPORT_KIND) {
      return { views: [], skipped: 0, error: "Bu videodevor ko'rinishlari fayli emas" };
    }
    if (typeof record.version !== 'number' || record.version > VIEWS_EXPORT_VERSION) {
      return { views: [], skipped: 0, error: "Fayl versiyasi qo'llab-quvvatlanmaydi" };
    }
    items = record.views;
  }
  if (!Array.isArray(items)) {
    return { views: [], skipped: 0, error: "Faylda ko'rinishlar ro'yxati topilmadi" };
  }
  const views = sanitizeViews(items);
  const skipped = items.length - views.length;
  if (views.length === 0) {
    return { views: [], skipped, error: "Faylda yaroqli ko'rinish topilmadi" };
  }
  return { views, skipped, error: null };
}

/** Import: bir xil id — yangilanadi (joyida), yangilari oxiriga qo'shiladi.
 * Umumiy son MAX_VIEWS bilan cheklanadi. */
export function mergeViews(existing: readonly WallView[], incoming: readonly WallView[]): WallView[] {
  const byId = new Map(incoming.map((view) => [view.id, view]));
  const merged = existing.map((view) => byId.get(view.id) ?? view);
  const known = new Set(existing.map((view) => view.id));
  for (const view of incoming) {
    if (!known.has(view.id)) merged.push(view);
  }
  return merged.slice(0, MAX_VIEWS);
}

/** Ko'rinish nomi bandmi (katta-kichik harfsiz, bo'shliqlarsiz). */
export function isViewNameTaken(views: readonly WallView[], name: string, exceptId?: string): boolean {
  const key = name.trim().toLocaleLowerCase();
  return views.some((view) => view.id !== exceptId && view.name.trim().toLocaleLowerCase() === key);
}

/** Joriy holat (tanlangan setka + kataklar) — localStorage'dan tekshirib o'qish. */
export interface WallState {
  layout: WallLayout;
  tiles: WallTiles;
}

export function sanitizeWallState(raw: unknown, fallback: WallLayout = '2x2'): WallState {
  const value = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const layout = isWallLayout(value.layout) ? value.layout : fallback;
  const view = sanitizeView({ id: 'current', name: 'current', layout, tiles: Array.isArray(value.tiles) ? value.tiles : [] });
  return { layout, tiles: view ? view.tiles : emptyTiles(layoutCapacity(layout)) };
}

// ---------------------------------------------------------------------------
// Kameralar ro'yxati filtri (yon panel va "ro'yxat bo'yicha" sahifalash)
// ---------------------------------------------------------------------------

export type WallStatusFilter = 'all' | 'live' | 'offline';

export interface WallCameraFilters {
  search: string;
  /** Bino nomi; '' — hammasi. */
  building: string;
  /** Qavat: '' — hammasi, 'none' — belgilanmagan, aks holda raqam matni. */
  floor: string;
  status: WallStatusFilter;
}

export const EMPTY_WALL_FILTERS: WallCameraFilters = { search: '', building: '', floor: '', status: 'all' };

export interface FilterableCamera {
  id: string;
  name: string;
  zone: string;
  building: string;
  status: string;
  floor?: number | null;
  hasVideo?: boolean;
}

/** Jonli va tasvir kelayotgan kamera — devorda o'ynatish mumkin. */
export function isCameraOnline(camera: FilterableCamera): boolean {
  return camera.status === 'live' && camera.hasVideo !== false;
}

export function filterCameras<T extends FilterableCamera>(cameras: readonly T[], filters: WallCameraFilters): T[] {
  const query = filters.search.trim().toLocaleLowerCase();
  return cameras.filter((camera) => {
    if (filters.building && camera.building !== filters.building) return false;
    if (filters.floor) {
      const floor = camera.floor ?? null;
      if (filters.floor === 'none' ? floor !== null : String(floor) !== filters.floor) return false;
    }
    if (filters.status === 'live' && !isCameraOnline(camera)) return false;
    if (filters.status === 'offline' && isCameraOnline(camera)) return false;
    if (query) {
      const haystack = `${camera.name} ${camera.zone} ${camera.building}`.toLocaleLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

/** Tanlangan bino kameralaridagi qavatlar (o'sish tartibida, belgilanmagan — oxirida). */
export function floorOptions(cameras: readonly FilterableCamera[], building: string): Array<number | null> {
  const floors = new Set<number | null>();
  for (const camera of cameras) {
    if (building && camera.building !== building) continue;
    floors.add(camera.floor ?? null);
  }
  return [...floors].sort((a, b) => (a === null ? 1 : b === null ? -1 : a - b));
}

// ---------------------------------------------------------------------------
// Yon paneldagi daraxt: bino → qavat → kamera
// ---------------------------------------------------------------------------

/** Daraxtning bitta tuguni (bino yoki qavat) va undagi kamera sanoqlari. */
export interface CameraGroup {
  /** Filtrga yoziladigan qiymat: bino nomi yoki qavat kaliti ('none' / '3'). */
  key: string;
  label: string;
  total: number;
  /** Shulardan nechtasi tasvir bermoqda. */
  online: number;
}

/** Bino nomi bo'sh bo'lsa ham ro'yxatda o'z qatori bo'lsin. */
export const NO_BUILDING_LABEL = 'Bino belgilanmagan';

export function floorLabel(floor: number | null): string {
  return floor === null ? 'Qavat belgilanmagan' : `${floor}-qavat`;
}

/** Qavat kaliti `WallCameraFilters.floor` ko'rinishida. */
export function floorFilterKey(floor: number | null): string {
  return floor === null ? 'none' : String(floor);
}

function countGroup<T extends FilterableCamera>(cameras: readonly T[]): { total: number; online: number } {
  let online = 0;
  for (const camera of cameras) if (isCameraOnline(camera)) online += 1;
  return { total: cameras.length, online };
}

/** Binolar ro'yxati — qidiruv va holat filtri hisobga olingan holda.
 *  Bino/qavat filtri e'tiborga olinmaydi: daraxtning yuqori darajasi. */
export function buildingGroups<T extends FilterableCamera>(cameras: readonly T[], filters: WallCameraFilters): CameraGroup[] {
  const scoped = filterCameras(cameras, { ...filters, building: '', floor: '' });
  const map = new Map<string, T[]>();
  for (const camera of scoped) {
    const key = camera.building || '';
    const list = map.get(key);
    if (list) list.push(camera);
    else map.set(key, [camera]);
  }
  return [...map.entries()]
    .map(([key, list]) => ({ key, label: key || NO_BUILDING_LABEL, ...countGroup(list) }))
    // Nomi yo'q bino — oxirida.
    .sort((a, b) => (a.key === '' ? 1 : b.key === '' ? -1 : a.label.localeCompare(b.label)));
}

/** Tanlangan binodagi qavatlar — qidiruv va holat filtri hisobga olingan holda. */
export function floorGroups<T extends FilterableCamera>(cameras: readonly T[], filters: WallCameraFilters): CameraGroup[] {
  const scoped = filterCameras(cameras, { ...filters, floor: '' });
  return floorOptions(scoped, '').map((floor) => ({
    key: floorFilterKey(floor),
    label: floorLabel(floor),
    ...countGroup(scoped.filter((camera) => (camera.floor ?? null) === floor)),
  }));
}
