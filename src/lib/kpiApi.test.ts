import { describe, expect, it } from 'vitest';
import {
  formatMinutes,
  formatPct,
  kpiGroups,
  kpiPath,
  parseChatIds,
  scheduleLabel,
  trendOf,
  type KpiReport,
} from './kpiApi';
import { readState, writeState } from './hisobotApi';

const att = (rate: number | null, prevRate: number | null, latePct: number | null, prevLatePct: number | null) => ({
  rate, prevRate, latePct, prevLatePct, present: 0, late: 0, absent: 0, daysCovered: 0,
});

const REPORT: KpiReport = {
  period: { from: '2026-09-14', to: '2026-09-20', days: 7 },
  attendance: {
    staff: att(92, 88, 20, 10),
    students: att(70, null, 4, 4),
    previous: { from: '2026-09-07', to: '2026-09-13' },
  },
  recognition: {
    studentsCoverage: 50, staffCoverage: 95, studentsEnrolled: 5, studentsTotal: 10, staffEnrolled: 19, staffTotal: 20,
    recognisedDailyPct: 80, unknownPending: 3,
  },
  security: {
    events: 10, reviewed: 8, rejected: 4, confirmed: 4, open: 2, falsePct: 50, reviewMinutes: 12, resolveMinutes: 150,
    modules: [],
  },
  infrastructure: { camerasTotal: 12, camerasActive: 10, camerasOnline: 8, videoFlowing: 6, onlinePct: 80 },
};

describe('trendOf', () => {
  it('yuqori yaxshi bo‘lgan ko‘rsatkich', () => {
    expect(trendOf(92, 88)).toEqual({ dir: 'up', delta: 4, good: true });
    expect(trendOf(80, 88)).toEqual({ dir: 'down', delta: -8, good: false });
  });
  it('kam yaxshi bo‘lgan ko‘rsatkich (kechikish)', () => {
    expect(trendOf(20, 10, false)).toEqual({ dir: 'up', delta: 10, good: false });
    expect(trendOf(5, 10, false)?.good).toBe(true);
  });
  it('o‘zgarmagan va yo‘q qiymat', () => {
    expect(trendOf(4, 4)).toEqual({ dir: 'flat', delta: 0, good: null });
    expect(trendOf(70, null)).toBeNull();
    expect(trendOf(null, 70)).toBeNull();
  });
  it('kasr xatosini yaxlitlaydi', () => {
    expect(trendOf(90.3, 90.1)?.delta).toBe(0.2);
  });
});

describe('formatlash', () => {
  it('daqiqa va soat', () => {
    expect(formatMinutes(null)).toBe('—');
    expect(formatMinutes(12.4)).toBe('12 daq');
    expect(formatMinutes(150)).toBe('2.5 soat');
  });
  it('foiz', () => {
    expect(formatPct(null)).toBe('—');
    expect(formatPct(66.66)).toBe('66.7%');
  });
  it('KPI yo‘li', () => {
    expect(kpiPath('2026-09-01', '2026-09-07')).toBe('/api/kpi?dan=2026-09-01&gacha=2026-09-07');
  });
});

describe('kpiGroups', () => {
  const groups = kpiGroups(REPORT);
  const tile = (key: string) => groups.flatMap((g) => g.tiles).find((t) => t.key === key)!;

  it('to‘rt guruh', () => {
    expect(groups.map((g) => g.title)).toEqual(['Davomat', 'Yuzni tanish', 'Xavfsizlik', 'Kameralar']);
  });
  it('svetofor: davomat, kechikish (teskari), yolg‘on signal, kameralar', () => {
    expect(tile('staffRate').rag).toBe('yashil');
    expect(tile('studentsRate').rag).toBe('qizil');
    expect(tile('staffLate').rag).toBe('qizil');
    expect(tile('studentsLate').rag).toBe('yashil');
    expect(tile('false').rag).toBe('qizil');
    expect(tile('review').rag).toBe('yashil');
    expect(tile('online').rag).toBe('sariq');
    expect(tile('unknown').rag).toBe('yoq');
  });
  it('trend o‘qi va izohlar', () => {
    expect(tile('staffRate').trend).toEqual({ dir: 'up', delta: 4, good: true });
    expect(tile('staffLate').trend?.good).toBe(false);
    expect(tile('studentsRate').trend).toBeNull();
    expect(tile('online').hint).toBe('8/10');
    expect(tile('resolve').value).toBe('2.5 soat');
  });
});

describe('avtomatik yuborish', () => {
  it('chat ID larni ajratadi va tekshiradi', () => {
    expect(parseChatIds('12345\n-100777, 12345')).toEqual({ ids: ['12345', '-100777'], error: null });
    expect(parseChatIds('@rektorat_kanal').ids).toEqual(['@rektorat_kanal']);
    expect(parseChatIds('').error).toBe('Kamida bitta chat ID kiriting');
    expect(parseChatIds('12345\nsalom dunyo').error).toMatch(/noto'g'ri/);
  });
  it('qisqa tavsif', () => {
    expect(scheduleLabel({ kind: 'haftalik', report: 'kpi' })).toBe('Haftalik · KPI');
    expect(scheduleLabel({ kind: 'oylik', report: 'tabel_xodim' })).toBe('Oylik · Xodimlar tabeli');
  });
});

describe('KPI ko‘rinishi URL’da', () => {
  it('o‘qiladi va yoziladi; ro‘yxat ham saqlanadi', () => {
    expect(readState(new URLSearchParams('korinish=kpi'), '2026-09-24').view).toBe('kpi');
    expect(writeState(new URLSearchParams(), { view: 'kpi' }).get('korinish')).toBe('kpi');
    expect(writeState(new URLSearchParams(), { view: 'royxat' }).get('korinish')).toBe('royxat');
    expect(writeState(new URLSearchParams('korinish=kpi'), { view: 'taxta' }).has('korinish')).toBe(false);
  });
});
