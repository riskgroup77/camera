import { describe, expect, it } from 'vitest';
import { liveLink, similarityPercent, stopDuration, stopPlace, stopTimeRange } from './personLocatorApi';

describe('personLocator helpers', () => {
  it('jonli havola faqat kamera parametrini beradi', () => {
    expect(liveLink('cam-1')).toBe('/videodevor?kamera=cam-1');
  });


  it('o‘xshashlik foizi', () => {
    expect(similarityPercent(0.634)).toBe('63%');
    expect(similarityPercent(1.2)).toBe('100%');
    expect(similarityPercent(null)).toBe('—');
  });

  it('to‘xtash vaqti va davomiyligi', () => {
    const stop = { startedAt: '2026-09-23T04:00:00Z', endedAt: '2026-09-23T04:05:00Z' };
    expect(stopTimeRange(stop)).toBe('09:00–09:05');
    expect(stopDuration(stop)).toBe('5 daq');
    expect(stopTimeRange({ startedAt: stop.startedAt, endedAt: stop.startedAt })).toBe('09:00');
    expect(stopDuration({ startedAt: stop.startedAt, endedAt: stop.startedAt })).toBeNull();
    expect(stopDuration({ startedAt: stop.startedAt, endedAt: '2026-09-23T05:10:00Z' })).toBe('1 soat 10 daq');
  });

  it('joy matni', () => {
    expect(stopPlace({ building: 'Bosh bino', floor: 2, zone: null })).toBe('Bosh bino · 2-qavat');
    expect(stopPlace({ building: null, floor: null, zone: null })).toBeNull();
  });
});
