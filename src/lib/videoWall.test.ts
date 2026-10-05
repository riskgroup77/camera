import { describe, expect, it } from 'vitest';
import {
  EMPTY_WALL_FILTERS,
  WALL_LAYOUTS,
  buildingGroups,
  filterCameras,
  floorGroups,
  floorOptions,
  addToFirstEmpty,
  clampPage,
  isViewNameTaken,
  layoutCapacity,
  layoutForKey,
  layoutGeometry,
  mergeViews,
  nextTourView,
  normalizeTourInterval,
  pageCount,
  pageTiles,
  parseViewsImport,
  placeCamera,
  planPlayback,
  pruneCameraIds,
  pruneTiles,
  pruneTilesIfKnown,
  removeAt,
  resizeTiles,
  sanitizeView,
  sanitizeViews,
  sanitizeWallState,
  serializeViews,
  stepPage,
  swapTiles,
  tourSequence,
  type WallView,
} from './videoWall';

function view(id: string, name = id, overrides: Partial<WallView> = {}): WallView {
  return { id, name, layout: '2x2', tiles: ['a', null, 'b', null], updatedAt: '2026-09-19T08:00:00.000Z', ...overrides };
}

describe('setka geometriyasi', () => {
  it('kvadrat setkalar sig\'imi', () => {
    expect(['1x1', '2x2', '3x3', '4x4', '5x5'].map((l) => layoutCapacity(l as never))).toEqual([1, 4, 9, 16, 25]);
  });

  it('1+5: 3x3 setkada 2x2 katta katak va 5 ta kichik', () => {
    const g = layoutGeometry('1+5');
    expect(g.cols).toBe(3);
    expect(g.cells).toHaveLength(6);
    expect(g.cells[0]).toEqual({ index: 0, col: 0, row: 0, colSpan: 2, rowSpan: 2 });
    expect(g.cells.slice(1).map((c) => [c.col, c.row])).toEqual([
      [2, 0],
      [2, 1],
      [0, 2],
      [1, 2],
      [2, 2],
    ]);
  });

  it('1+7: 4x4 setkada 3x3 katta katak va 7 ta kichik', () => {
    const g = layoutGeometry('1+7');
    expect(g.cells).toHaveLength(8);
    expect(g.cells[0].colSpan).toBe(3);
  });

  it('har setkada kataklar bir-birini qoplamaydi va setkani to\'liq to\'ldiradi', () => {
    for (const layout of WALL_LAYOUTS) {
      const g = layoutGeometry(layout);
      const covered = new Set<string>();
      for (const cell of g.cells) {
        for (let c = cell.col; c < cell.col + cell.colSpan; c += 1) {
          for (let r = cell.row; r < cell.row + cell.rowSpan; r += 1) {
            const key = `${c}:${r}`;
            expect(covered.has(key), `${layout} ${key}`).toBe(false);
            covered.add(key);
          }
        }
      }
      expect(covered.size).toBe(g.cols * g.rows);
      expect(g.cells.map((c) => c.index)).toEqual(g.cells.map((_, i) => i));
    }
  });

  it('klaviatura tugmalari', () => {
    expect(layoutForKey('1')).toBe('1x1');
    expect(layoutForKey('5')).toBe('5x5');
    expect(layoutForKey('7')).toBe('1+7');
    expect(layoutForKey('8')).toBeNull();
  });
});

describe('kataklar', () => {
  it('kattalashganda joylar saqlanadi', () => {
    expect(resizeTiles(['a', null, 'b', null], 9)).toEqual(['a', null, 'b', null, null, null, null, null, null]);
  });

  it('kichrayganda sig\'sa — joyida, sig\'masa — zichlanadi', () => {
    expect(resizeTiles(['a', 'b', null, null], 2)).toEqual(['a', 'b']);
    expect(resizeTiles(['a', null, null, 'b'], 2)).toEqual(['a', 'b']);
    expect(resizeTiles(['a', 'b', 'c', 'd'], 1)).toEqual(['a']);
  });

  it('bir kamera ikki katakda bo\'lmaydi — almashadi', () => {
    expect(placeCamera(['a', 'b', null], 2, 'a')).toEqual([null, 'b', 'a']);
    expect(placeCamera(['a', 'b', null], 1, 'a')).toEqual(['b', 'a', null]);
    expect(placeCamera(['a', null], 0, 'a')).toEqual(['a', null]);
    expect(placeCamera(['a'], 5, 'x')).toEqual(['a']);
  });

  it('birinchi bo\'sh katakka qo\'shish', () => {
    expect(addToFirstEmpty(['a', null, null], 'b')).toEqual({ tiles: ['a', 'b', null], index: 1 });
    expect(addToFirstEmpty(['a', 'b'], 'b')).toEqual({ tiles: ['a', 'b'], index: 1 });
    expect(addToFirstEmpty(['a', 'b'], 'c')).toBeNull();
  });

  it('o\'chirish, almashtirish, eskirganlarni tozalash', () => {
    expect(removeAt(['a', 'b'], 0)).toEqual([null, 'b']);
    expect(swapTiles(['a', null, 'c'], 0, 2)).toEqual(['c', null, 'a']);
    const tiles = ['a', 'x', null];
    expect(pruneTiles(tiles, new Set(['a']))).toEqual(['a', null, null]);
    expect(pruneTiles(tiles, new Set(['a', 'x']))).toBe(tiles);
  });

  it("ishonchsiz ro'yxat kataklarni bo'shatmaydi", () => {
    const tiles = ['a', 'x', null];
    // Ro'yxat hali kelmagan yoki so'rov xato bergan — tegilmaydi.
    expect(pruneTilesIfKnown(tiles, null)).toBe(tiles);
    // Bo'sh javob ham "hamma kamera o'chirilgan" degani emas.
    expect(pruneTilesIfKnown(tiles, new Set())).toBe(tiles);
    // Ishonchli ro'yxat — endi yo'q kamera katakdan olinadi.
    expect(pruneTilesIfKnown(tiles, new Set(['a']))).toEqual(['a', null, null]);
  });

  it("kamera identifikatorlari ro'yxati ham xuddi shu qoida bilan tozalanadi", () => {
    const ids = ['a', 'x'];
    expect(pruneCameraIds(ids, null)).toBe(ids);
    expect(pruneCameraIds(ids, new Set())).toBe(ids);
    expect(pruneCameraIds(ids, new Set(['a', 'x']))).toBe(ids);
    expect(pruneCameraIds(ids, new Set(['a']))).toEqual(['a']);
  });
});

describe('sahifalash', () => {
  const ids = Array.from({ length: 10 }, (_, i) => `c${i}`);

  it('sahifalar soni va kesimi', () => {
    expect(pageCount(10, 4)).toBe(3);
    expect(pageCount(0, 4)).toBe(1);
    expect(pageTiles(ids, 4, 2)).toEqual(['c8', 'c9', null, null]);
    expect(pageTiles(ids, 4, 99)).toEqual(['c8', 'c9', null, null]);
  });

  it('aylanma qadam', () => {
    expect(stepPage(2, 1, 10, 4)).toBe(0);
    expect(stepPage(0, -1, 10, 4)).toBe(2);
    expect(clampPage(-3, 10, 4)).toBe(0);
    expect(clampPage(Number.NaN, 10, 4)).toBe(0);
  });
});

describe('tur (aylanish)', () => {
  it('ko\'rinishlar ketma-ketligi aylanma', () => {
    expect(nextTourView(['a', 'b', 'c'], 'a')).toBe('b');
    expect(nextTourView(['a', 'b', 'c'], 'c')).toBe('a');
    expect(nextTourView(['a', 'b'], 'noma\'lum')).toBe('a');
    expect(nextTourView(['a', 'b'], null)).toBe('a');
    expect(nextTourView([], 'a')).toBeNull();
  });

  it('tanlanganlar saqlangan tartibda, hech biri bo\'lmasa — hammasi', () => {
    const views = [view('a'), view('b'), view('c')];
    expect(tourSequence(views, ['c', 'a'])).toEqual(['a', 'c']);
    expect(tourSequence(views, ['yo\'q'])).toEqual(['a', 'b', 'c']);
    expect(tourSequence(views, [])).toEqual(['a', 'b', 'c']);
  });

  it('interval chegaralari', () => {
    expect(normalizeTourInterval(1)).toBe(5);
    expect(normalizeTourInterval(9999)).toBe(600);
    expect(normalizeTourInterval('30')).toBe(30);
    expect(normalizeTourInterval('abc')).toBe(20);
  });
});

describe('jonli oqim rejasi', () => {
  const playable = (id: string) => id !== 'off';

  it('chegaradan oshganlari kadr (rasm) ko\'rsatadi', () => {
    const tiles = ['a', 'b', 'off', null, 'c'];
    expect(planPlayback({ tiles, isPlayable: playable, maximized: null, featured: false, maxLive: 2 })).toEqual([
      'live',
      'live',
      'offline',
      'empty',
      'snapshot',
    ]);
  });

  it('1+N setkada katta katak ustuvor', () => {
    const tiles = ['big', 'a', 'b'];
    const plan = planPlayback({ tiles, isPlayable: playable, maximized: null, featured: true, maxLive: 1 });
    expect(plan).toEqual(['live', 'snapshot', 'snapshot']);
  });

  it('kattalashtirilganda faqat bitta katak', () => {
    const plan = planPlayback({ tiles: ['a', 'b', 'c'], isPlayable: playable, maximized: 1, featured: false });
    expect(plan).toEqual(['hidden', 'live', 'hidden']);
  });

  it('varaq fonda — hech narsa jonli emas', () => {
    const plan = planPlayback({ tiles: ['a', 'off'], isPlayable: playable, maximized: null, featured: false, paused: true });
    expect(plan).toEqual(['snapshot', 'offline']);
    expect(planPlayback({ tiles: ['a'], isPlayable: playable, maximized: 0, featured: false, paused: true })).toEqual([
      'snapshot',
    ]);
  });
});

describe('ko\'rinishlarni saqlash va tekshirish', () => {
  it('yaroqsiz ko\'rinishlar tashlanadi', () => {
    expect(sanitizeView(null)).toBeNull();
    expect(sanitizeView({ ...view('a'), layout: '6x6' })).toBeNull();
    expect(sanitizeView({ ...view('a'), name: '   ' })).toBeNull();
    expect(sanitizeView({ ...view('a'), id: '../../x' })).toBeNull();
    expect(sanitizeView({ ...view('a'), tiles: 'a,b' })).toBeNull();
  });

  it('kataklar sig\'imga moslanadi, takror va noto\'g\'ri turlar bo\'shatiladi', () => {
    const cleaned = sanitizeView({
      id: 'v1',
      name: '  Kirish  ',
      layout: '2x2',
      tiles: ['a', 'a', 42, 'b', 'c', 'd'],
      updatedAt: 'emas-sana',
    });
    expect(cleaned).toEqual({
      id: 'v1',
      name: 'Kirish',
      layout: '2x2',
      tiles: ['a', null, null, 'b'],
      updatedAt: new Date(0).toISOString(),
    });
  });

  it('takrorlangan id — birinchisi qoladi', () => {
    expect(sanitizeViews([view('a', 'Bir'), view('a', 'Ikki'), 'x']).map((v) => v.name)).toEqual(['Bir']);
    expect(sanitizeViews('buzilgan')).toEqual([]);
  });

  it('eksport -> import aylanib qaytadi', () => {
    const views = [view('a', 'Birinchi qavat'), view('b', 'Hovli', { layout: '1+5', tiles: ['x', null, null, null, null, 'y'] })];
    const text = serializeViews(views, new Date('2026-09-19T10:00:00Z'));
    expect(JSON.parse(text).kind).toBe('situatsion-markaz/videodevor');
    const parsed = parseViewsImport(text);
    expect(parsed.error).toBeNull();
    expect(parsed.views).toEqual(views);
  });

  it('import xatolari', () => {
    expect(parseViewsImport('{buzuq').error).toMatch(/JSON/);
    expect(parseViewsImport('{"kind":"boshqa","views":[]}').error).toMatch(/emas/);
    expect(parseViewsImport('{"kind":"situatsion-markaz/videodevor","version":99,"views":[]}').error).toMatch(/versiya/);
    const partial = parseViewsImport(JSON.stringify([view('a'), { id: 'b' }]));
    expect(partial.views).toHaveLength(1);
    expect(partial.skipped).toBe(1);
    expect(parseViewsImport('[]').error).toMatch(/yaroqli/);
  });

  it('import birlashtirish: bir xil id yangilanadi, yangilari oxiriga', () => {
    const merged = mergeViews([view('a', 'Eski'), view('b')], [view('a', 'Yangi'), view('c')]);
    expect(merged.map((v) => `${v.id}:${v.name}`)).toEqual(['a:Yangi', 'b:b', 'c:c']);
  });

  it('nom bandligi', () => {
    const views = [view('a', 'Hovli')];
    expect(isViewNameTaken(views, ' hovli ')).toBe(true);
    expect(isViewNameTaken(views, 'Hovli', 'a')).toBe(false);
  });

  it('joriy holat tekshiruvi', () => {
    expect(sanitizeWallState({ layout: '1x1', tiles: ['a', 'b'] })).toEqual({ layout: '1x1', tiles: ['a'] });
    expect(sanitizeWallState('buzuq')).toEqual({ layout: '2x2', tiles: [null, null, null, null] });
  });
});

describe('kamera filtri', () => {
  const cams = [
    { id: '1', name: 'Kirish', zone: 'Foye', building: 'A', status: 'live', floor: 1 },
    { id: '2', name: 'Zal', zone: '101-xona', building: 'A', status: 'offline', floor: 1 },
    { id: '3', name: 'Hovli', zone: 'Tashqi', building: 'B', status: 'live', floor: null },
    { id: '4', name: 'Dahliz', zone: 'Koridor', building: 'B', status: 'live', floor: 2, hasVideo: false },
  ];
  const ids = (list: { id: string }[]) => list.map((c) => c.id);

  it('bino, qavat, holat va qidiruv', () => {
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, building: 'A' }))).toEqual(['1', '2']);
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, floor: 'none' }))).toEqual(['3']);
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, floor: '2' }))).toEqual(['4']);
    // Tasvirsiz kamera "onlayn" hisoblanmaydi.
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, status: 'live' }))).toEqual(['1', '3']);
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, status: 'offline' }))).toEqual(['2', '4']);
    expect(ids(filterCameras(cams, { ...EMPTY_WALL_FILTERS, search: '  XONA ' }))).toEqual(['2']);
  });

  it('qavatlar ro\'yxati', () => {
    expect(floorOptions(cams, '')).toEqual([1, 2, null]);
    expect(floorOptions(cams, 'B')).toEqual([2, null]);
  });

  it('yon panel daraxti: binolar va ularning sanoqlari', () => {
    expect(buildingGroups(cams, EMPTY_WALL_FILTERS)).toEqual([
      { key: 'A', label: 'A', total: 2, online: 1 },
      { key: 'B', label: 'B', total: 2, online: 1 },
    ]);
    // Qidiruv va holat filtri sanoqlarga ta'sir qiladi, bino tanlovi — yo'q.
    expect(buildingGroups(cams, { ...EMPTY_WALL_FILTERS, status: 'live', building: 'A' })).toEqual([
      { key: 'A', label: 'A', total: 1, online: 1 },
      { key: 'B', label: 'B', total: 1, online: 1 },
    ]);
    expect(buildingGroups(cams, { ...EMPTY_WALL_FILTERS, search: 'hovli' })).toEqual([
      { key: 'B', label: 'B', total: 1, online: 1 },
    ]);
  });

  it("nomsiz bino oxirida, o'z yorlig'i bilan turadi", () => {
    const withNone = [...cams, { id: '5', name: 'Ombor', zone: '', building: '', status: 'live', floor: 1 }];
    expect(buildingGroups(withNone, EMPTY_WALL_FILTERS).map((g) => g.label)).toEqual(['A', 'B', 'Bino belgilanmagan']);
  });

  it('yon panel daraxti: tanlangan binodagi qavatlar', () => {
    expect(floorGroups(cams, { ...EMPTY_WALL_FILTERS, building: 'B' })).toEqual([
      { key: '2', label: '2-qavat', total: 1, online: 0 },
      { key: 'none', label: 'Qavat belgilanmagan', total: 1, online: 1 },
    ]);
    // Qavat tanlangan bo'lsa ham ro'yxat qisqarmaydi — yonma-yon o'tish uchun.
    expect(floorGroups(cams, { ...EMPTY_WALL_FILTERS, building: 'B', floor: '2' }).map((g) => g.key)).toEqual(['2', 'none']);
  });
});
