import { describe, expect, it } from 'vitest';
import {
  buildingOptions,
  cameraStats,
  filterCameras,
  floorLabel,
  floorOptions,
  isStreaming,
  layoutColumns,
  pickMosaic,
  rankCameras,
} from './cameraPick';
import { nextFlowState, type FlowState } from './useVideoFlow';
import type { CameraFeed } from '../types';

function camera(patch: Partial<CameraFeed> & { id: string }): CameraFeed {
  return {
    name: patch.id,
    building: '1-bino',
    zone: '',
    status: 'live',
    streamUrl: 'https://x/s.m3u8',
    ...patch,
  } as CameraFeed;
}

describe('isStreaming', () => {
  it('faqat ulangan, kadrli va havolali kamera', () => {
    expect(isStreaming(camera({ id: 'a' }))).toBe(true);
    expect(isStreaming(camera({ id: 'b', hasVideo: false }))).toBe(false);
    expect(isStreaming(camera({ id: 'c', status: 'offline' }))).toBe(false);
    expect(isStreaming(camera({ id: 'd', streamUrl: undefined }))).toBe(false);
  });
});

describe('cameraStats', () => {
  it('oqim, ulangan va jami alohida sanaladi', () => {
    const list = [
      camera({ id: 'a' }),
      camera({ id: 'b', hasVideo: false }),
      camera({ id: 'c', status: 'offline' }),
    ];
    expect(cameraStats(list)).toEqual({ flowing: 1, live: 2, total: 3 });
    expect(cameraStats([])).toEqual({ flowing: 0, live: 0, total: 0 });
  });
});

describe('rankCameras / pickMosaic', () => {
  it('oqim beradiganlar oldinda, keyin nom bo‘yicha', () => {
    const list = [
      camera({ id: 'off', name: 'A', status: 'offline' }),
      camera({ id: 'novideo', name: 'B', hasVideo: false }),
      camera({ id: 'live2', name: 'Z' }),
      camera({ id: 'live1', name: 'C' }),
    ];
    expect(rankCameras(list).map((item) => item.id)).toEqual(['live1', 'live2', 'novideo', 'off']);
  });

  it('mozaika ko‘pi bilan 4 ta katak beradi', () => {
    const list = Array.from({ length: 9 }, (_, index) => camera({ id: `c${index}`, name: `C${index}` }));
    expect(pickMosaic(list, 4)).toHaveLength(4);
    expect(pickMosaic(list.slice(0, 2), 4)).toHaveLength(2);
    expect(pickMosaic(list, 0)).toHaveLength(0);
  });

  it('asl ro‘yxat o‘zgarmaydi', () => {
    const list = [camera({ id: 'b', name: 'B' }), camera({ id: 'a', name: 'A' })];
    rankCameras(list);
    expect(list.map((item) => item.id)).toEqual(['b', 'a']);
  });
});

describe('filterCameras', () => {
  const list = [
    camera({ id: '1', name: 'Kirish eshigi', building: '1-bino', floor: 1, zone: 'Dahliz' }),
    camera({ id: '2', name: 'Yo‘lak', building: '2-bino', floor: 3, department: 'Matematika' }),
    camera({ id: '3', name: 'Hovli', building: '2-bino', floor: null }),
  ];

  it('nom, zona va kafedra bo‘yicha qidiradi', () => {
    expect(filterCameras(list, { q: 'kirish', building: '', floor: '' }).map((c) => c.id)).toEqual(['1']);
    expect(filterCameras(list, { q: 'dahliz', building: '', floor: '' }).map((c) => c.id)).toEqual(['1']);
    expect(filterCameras(list, { q: 'matem', building: '', floor: '' }).map((c) => c.id)).toEqual(['2']);
  });

  it('bino va qavat kesimi', () => {
    expect(filterCameras(list, { q: '', building: '2-bino', floor: '' }).map((c) => c.id)).toEqual(['2', '3']);
    expect(filterCameras(list, { q: '', building: '', floor: 'none' }).map((c) => c.id)).toEqual(['3']);
    expect(filterCameras(list, { q: '', building: '', floor: '3' }).map((c) => c.id)).toEqual(['2']);
    expect(filterCameras(list, { q: 'hovli', building: '1-bino', floor: '' })).toEqual([]);
  });

  it('bo‘sh filtr hammasini qaytaradi', () => {
    expect(filterCameras(list, { q: '  ', building: '', floor: '' })).toHaveLength(3);
  });
});

describe('options', () => {
  const list = [
    camera({ id: '1', building: '2-bino', floor: 2 }),
    camera({ id: '2', building: '1-bino', floor: 10 }),
    camera({ id: '3', building: '1-bino', floor: null }),
  ];

  it('binolar takrorlanmaydi va tartiblanadi', () => {
    expect(buildingOptions(list)).toEqual(['1-bino', '2-bino']);
    expect(buildingOptions([])).toEqual([]);
  });

  it('qavatlar raqamli tartibda, noma’lumi oxirida', () => {
    expect(floorOptions(list)).toEqual(['2', '10', 'none']);
    expect(floorOptions([camera({ id: 'x', floor: 1 })])).toEqual(['1']);
    expect(floorOptions([])).toEqual([]);
  });

  it('qavat yorlig‘i', () => {
    expect(floorLabel('3')).toBe('3-qavat');
    expect(floorLabel('none')).toBe('Qavatsiz');
  });
});

describe('layoutColumns', () => {
  it('4/9/16 -> 2/3/4 ustun', () => {
    expect(layoutColumns(4)).toBe(2);
    expect(layoutColumns(9)).toBe(3);
    expect(layoutColumns(16)).toBe(4);
  });
});

describe('nextFlowState', () => {
  const limits = { startGraceMs: 10_000, stallAfterMs: 4_000 };
  const step = (prev: FlowState, progressed: boolean, sinceProgressMs: number, sinceStartMs: number) =>
    nextFlowState(prev, { progressed, sinceProgressMs, sinceStartMs }, limits);

  it('kadr siljisa — jonli', () => {
    expect(step('starting', true, 0, 500)).toBe('flowing');
    expect(step('stalled', true, 0, 60_000)).toBe('flowing');
  });

  it('boshlanish muddati ichida kutadi, keyin uziladi', () => {
    expect(step('starting', false, 3_000, 3_000)).toBe('starting');
    expect(step('starting', false, 11_000, 11_000)).toBe('stalled');
  });

  it('jonli oqim qisqa to‘xtashdan uzilgan deb belgilanmaydi', () => {
    expect(step('flowing', false, 2_000, 30_000)).toBe('flowing');
    expect(step('flowing', false, 5_000, 30_000)).toBe('stalled');
  });
});
