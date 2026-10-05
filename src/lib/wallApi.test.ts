import { describe, expect, it } from 'vitest';
import {
  buildWallQuery,
  burnInOffset,
  computeWallLayout,
  fitGrid,
  mergeArrival,
  mergeArrivalLists,
  nextRotationIndex,
  parseWallConfig,
  reconcileRotation,
  shiftIsoDate,
  sortFaces,
  type SpotlightItem,
} from './wallApi';

describe('parseWallConfig / buildWallQuery', () => {
  it('defaults', () => {
    expect(parseWallConfig('')).toEqual({ panels: ['A', 'B', 'C', 'D', 'E'], rotate: 15, cameras: [] });
    expect(buildWallQuery(parseWallConfig(''))).toBe('');
  });
  it('parses, normalises and drops junk', () => {
    const cfg = parseWallConfig('?panels=f,c,x,a&rotate=2&cameras=a,b,c,d,e');
    expect(cfg.panels).toEqual(['A', 'C', 'F']);
    expect(cfg.rotate).toBe(5);
    expect(cfg.cameras).toEqual(['a', 'b', 'c', 'd']);
  });
  it('round-trips', () => {
    const cfg = { panels: ['B', 'C', 'F'] as const, rotate: 30, cameras: ['x1', 'x2'] };
    const q = buildWallQuery({ ...cfg, panels: [...cfg.panels] });
    expect(q).toBe('?panels=B,C,F&rotate=30&cameras=x1,x2');
    expect(parseWallConfig(q)).toEqual({ ...cfg, panels: [...cfg.panels] });
  });
});

describe('computeWallLayout', () => {
  it('ultra-wide → one row in canonical order', () => {
    const l = computeWallLayout(['E', 'A', 'C'], 3840 / 1080);
    expect(l.areas).toBe('"A C E"');
    expect(l.rows).toBe('1fr');
    expect(l.columns.split(' ')).toHaveLength(3);
  });
  it('16:9 with all panels → C full-height second column', () => {
    const l = computeWallLayout(['A', 'B', 'C', 'D', 'E', 'F'], 16 / 9);
    expect(l.areas).toBe('"A C B F" "D C E F"');
  });
  it('16:9 default panels', () => {
    expect(computeWallLayout(['A', 'B', 'C', 'D', 'E'], 16 / 9).areas).toBe('"A C B" "D C E"');
  });
  it('without C', () => {
    expect(computeWallLayout(['A', 'B', 'D'], 16 / 9).areas).toBe('"A B" "D B"');
  });
  it('two panels stay in one row', () => {
    expect(computeWallLayout(['C', 'B'], 1.5).areas).toBe('"B C"');
  });
});

describe('rotation', () => {
  const items: SpotlightItem[] = [
    { kind: 'unit', id: 'u1', name: 'A', rate: 1 },
    { kind: 'group', id: 'G1', name: 'B', rate: 2 },
    { kind: 'unit', id: 'u2', name: 'C', rate: 3 },
  ];
  it('wraps', () => {
    expect(nextRotationIndex(2, 3)).toBe(0);
    expect(nextRotationIndex(0, 0)).toBe(0);
    expect(nextRotationIndex(5, 3)).toBe(0);
  });
  it('keeps the current item after list refresh', () => {
    expect(reconcileRotation('unit:u2', 0, items)).toBe(2);
    expect(reconcileRotation('unit:gone', 7, items)).toBe(2);
    expect(reconcileRotation(null, 1, [])).toBe(0);
  });
});

describe('fitGrid', () => {
  it('picks columns that maximise tile size', () => {
    const g = fitGrid(24, 1200, 600, 0.8, 0);
    expect(g.cols * g.rows).toBeGreaterThanOrEqual(24);
    expect(g.cols).toBe(8);
  });
  it('handles empty', () => {
    expect(fitGrid(0, 100, 100).tile).toBe(0);
  });
});

describe('lists', () => {
  it('sortFaces: arrivals first by time', () => {
    const r = sortFaces([
      { fullName: 'B', status: 'kelmadi', checkIn: null },
      { fullName: 'C', status: 'keldi', checkIn: '09:00' },
      { fullName: 'A', status: 'keldi', checkIn: '08:00' },
    ]);
    expect(r.map((x) => x.fullName)).toEqual(['A', 'C', 'B']);
  });
  it('mergeArrival dedups and limits', () => {
    expect(mergeArrival([{ id: '1' }, { id: '2' }], { id: '2' }, 2)).toEqual([{ id: '2' }, { id: '1' }]);
  });
  it('mergeArrivalLists keeps newer live items', () => {
    const server = [{ id: 'a', time: '09:00' }];
    const live = [{ id: 'b', time: '09:05' }, { id: 'c', time: '08:00' }, { id: 'a', time: '09:00' }];
    expect(mergeArrivalLists(server, live).map((x) => x.id)).toEqual(['b', 'a']);
  });
});

describe('misc', () => {
  it('burnInOffset stays within 2px and cycles', () => {
    for (let i = 0; i < 20; i++) {
      const [x, y] = burnInOffset(i);
      expect(Math.abs(x)).toBeLessThanOrEqual(2);
      expect(Math.abs(y)).toBeLessThanOrEqual(2);
    }
    expect(burnInOffset(9)).toEqual(burnInOffset(0));
  });
  it('shiftIsoDate', () => {
    expect(shiftIsoDate('2026-03-01', 1)).toBe('2026-02-28');
  });
});

describe('mergeArrivalLists vaqt formati', () => {
  it('server ISO vaqt qaytarsa ham jonli kelishlarni yo\'qotmaydi', () => {
    const server = [{ id: 's1', time: '2026-09-20T08:10:00' }];
    const live = [{ id: 'l1', time: '08:12' }];
    expect(mergeArrivalLists(server, live).map((a) => a.id)).toEqual(['l1', 's1']);
  });

  it('serverdan oldingi eski jonli yozuvni qo\'shmaydi', () => {
    const server = [{ id: 's1', time: '2026-09-20T08:10:00' }];
    const live = [{ id: 'l1', time: '08:05' }];
    expect(mergeArrivalLists(server, live).map((a) => a.id)).toEqual(['s1']);
  });
});
