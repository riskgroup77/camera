import { describe, expect, it } from 'vitest';
import { EVENT_CSV_HEADERS, csvDateTime, eventCsvRow, eventsCsvFilename } from './eventCsv';
import type { AIEvent } from '../../types';

const base: AIEvent = {
  id: 'e1',
  timestamp: '2026-09-20 14:20',
  cameraId: 'c1',
  cameraName: 'Kirish 1',
  building: '2-Bino',
  moduleCode: 12,
  moduleName: 'Taqiqlangan zona',
  group: 'xavfsizlik' as AIEvent['group'],
  confidence: 91,
  severity: 'yuqori',
  status: 'yangi',
};

describe('csvDateTime', () => {
  it('ISO vaqtni Excel o‘qiydigan ko‘rinishga keltiradi', () => {
    expect(csvDateTime('2026-09-20T12:00:00Z')).toBe('2026-09-20 12:00');
  });

  it('bo‘sh qiymat — bo‘sh katak', () => {
    expect(csvDateTime(null)).toBe('');
    expect(csvDateTime(undefined)).toBe('');
  });
});

describe('eventCsvRow', () => {
  it('ustunlar soni sarlavhalar soniga teng', () => {
    expect(eventCsvRow(base)).toHaveLength(EVENT_CSV_HEADERS.length);
  });

  it('muddat xom ISO emas, «Vaqt» ustuni bilan bir xil formatda', () => {
    const row = eventCsvRow({ ...base, dueAt: '2026-09-21T09:30:00Z' });
    const dueIndex = EVENT_CSV_HEADERS.indexOf('Muddat');
    expect(row[dueIndex]).toBe('2026-09-21 09:30');
  });

  it('bo‘sh maydonlar «undefined» emas, bo‘sh satr bo‘ladi', () => {
    const row = eventCsvRow(base);
    expect(row).not.toContain(undefined);
    expect(row[EVENT_CSV_HEADERS.indexOf('Shaxs')]).toBe('');
  });

  it('kadr havolasi (shaxsiy ma’lumot) faylga tushmaydi', () => {
    const row = eventCsvRow({ ...base, snapshotUrl: '/media/snap/e1.jpg' });
    expect(row.join('|')).not.toContain('/media/snap');
  });
});

describe('eventsCsvFilename', () => {
  it('fayl nomida soat ham bor — bir kunda bir nechta eksport ustma-ust tushmaydi', () => {
    const name = eventsCsvFilename('2026-09-20', new Date('2026-09-20T09:05:00Z'));
    expect(name).toMatch(/^hodisalar-2026-09-20-\d{2}-\d{2}\.csv$/);
    expect(name).not.toBe('hodisalar-2026-09-20.csv');
  });
});
