import { describe, expect, it } from 'vitest';
import {
  filterCameras,
  filterCounts,
  formatDuration,
  formatUptime,
  locationLabel,
  uptimeRag,
  type CameraHealthRow,
} from './cameraHealthApi';

function row(over: Partial<CameraHealthRow>): CameraHealthRow {
  return {
    id: 'x',
    name: 'Kamera',
    building: '1-Bino',
    floor: 2,
    ip: '10.0.0.1',
    status: 'online',
    lastSeenAt: null,
    lastFrameAt: null,
    offlineSince: null,
    uptimeDay: 100,
    uptimeWeek: 100,
    outagesWeek: 0,
    liveReady: true,
    recordingReady: true,
    recordingMbps: 0.5,
    aiLastAnalyzedAt: null,
    aiStream: null,
    ...over,
  };
}

const ROWS = [
  row({ id: 'a', name: 'Kirish', status: 'online' }),
  row({ id: 'b', name: 'Koridor', status: 'offline', recordingReady: false, ip: '10.0.0.2' }),
  row({ id: 'c', name: 'Zal', status: 'no_video', building: '2-Bino' }),
  row({ id: 'd', name: 'Hovli', status: 'online', recordingReady: null }),
];

describe('formatUptime', () => {
  it('formats with comma and keeps 100 whole', () => {
    expect(formatUptime(100)).toBe('100%');
    expect(formatUptime(99.97)).toBe('100%');
    expect(formatUptime(97.16)).toBe('97,1%');
    expect(formatUptime(50)).toBe('50%');
    expect(formatUptime(null)).toBe('—');
  });

  it('never rounds a real outage up to 100', () => {
    expect(formatUptime(99.94)).toBe('99,9%');
  });
});

describe('uptimeRag', () => {
  it('uses strict camera thresholds', () => {
    expect(uptimeRag(99.5)).toBe('yashil');
    expect(uptimeRag(96)).toBe('sariq');
    expect(uptimeRag(80)).toBe('qizil');
    expect(uptimeRag(undefined)).toBe('yoq');
  });
});

describe('filters', () => {
  it('filters by chip', () => {
    expect(filterCameras(ROWS, 'hammasi').map((r) => r.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(filterCameras(ROWS, 'oflayn').map((r) => r.id)).toEqual(['b']);
    expect(filterCameras(ROWS, 'tasvirsiz').map((r) => r.id)).toEqual(['c']);
    // Onlayn, lekin AI hech tekshirmagan (oflayn 'b' kirmaydi)
    expect(filterCameras(ROWS, 'ai_yoq').map((r) => r.id)).toEqual(['a', 'd']);
  });

  it('searches name, ip and building', () => {
    expect(filterCameras(ROWS, 'hammasi', 'kor').map((r) => r.id)).toEqual(['b']);
    expect(filterCameras(ROWS, 'hammasi', '10.0.0.2').map((r) => r.id)).toEqual(['b']);
    expect(filterCameras(ROWS, 'hammasi', '2-bino').map((r) => r.id)).toEqual(['c']);
  });

  it('counts every chip', () => {
    expect(filterCounts(ROWS)).toEqual({ hammasi: 4, oflayn: 1, tasvirsiz: 1, ai_yoq: 2 });
  });
});

describe('formatDuration', () => {
  it('scales units', () => {
    expect(formatDuration(42)).toBe('42 s');
    expect(formatDuration(12 * 60)).toBe('12 daq');
    expect(formatDuration(3 * 3600 + 5 * 60)).toBe('3 soat 5 daq');
    expect(formatDuration(2 * 3600)).toBe('2 soat');
    expect(formatDuration(2 * 86400 + 4 * 3600)).toBe('2 kun 4 soat');
  });
});

describe('locationLabel', () => {
  it('joins building and floor', () => {
    expect(locationLabel({ building: '1-Bino', floor: 3 })).toBe('1-Bino · 3-qavat');
    expect(locationLabel({ building: null, floor: null })).toBe('—');
  });
});
