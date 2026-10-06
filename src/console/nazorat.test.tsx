import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { GroupStudent } from '../lib/situationApi';
import { CAMERA_LOAD_MIN_MS, CAMERA_LOAD_MS, coverDone, resolutionLabel } from './panels/CamerasPanel';
import { clock } from './panels/GroupStatsPanel';
import PanelBoundary from './PanelBoundary';
import GroupsCriteriaTable, { sumSortValue } from '../components/situation/GroupsCriteriaTable';
import { NO_BUILDING, buildingCards, roomCards } from './cameraPick';
import type { CameraFeed } from '../types';
import { groupCounters, neighbourDay, studentMatches } from './panels/GroupTablePanel';
import { parseCounter } from './nazoratSelection';

function student(id: string, status: GroupStudent['status'], face = true): GroupStudent {
  return {
    id, fullName: id, photoUrl: null, initials: id.slice(0, 2), status, checkIn: null, checkOut: null,
    biometricsStatus: face ? 'tasdiqlangan' : 'yoq',
  };
}

function cam(id: string, building: string, floor: number | null, live = true): CameraFeed {
  return { id, name: id, building, zone: '', status: live ? 'live' : 'offline', streamUrl: live ? `/hls/${id}` : '', floor } as CameraFeed;
}

describe('kameralar: bino -> xona tanlovi', () => {
  const cameras = [cam('2-xona', 'B3', 2), cam('1-xona', 'B3', 1), cam('Hovli', '', null), cam('Oflayn', 'B3', 1, false), cam('Kirish', 'A', 1)];

  it('binolar — nomi, kameralar va jonlilar soni; binosizlar oxirida', () => {
    expect(buildingCards(cameras)).toEqual([
      { name: 'A', total: 1, streaming: 1 },
      { name: 'B3', total: 3, streaming: 2 },
      { name: NO_BUILDING, total: 1, streaming: 1 },
    ]);
  });

  it('bino xonalari — avval tasvir uzatayotganlar, qavat va nomi bo‘yicha', () => {
    expect(roomCards(cameras, 'B3').map((c) => c.id)).toEqual(['1-xona', '2-xona', 'Oflayn']);
    expect(roomCards(cameras, NO_BUILDING).map((c) => c.id)).toEqual(['Hovli']);
  });

  it('video ~5 soniya yuklanish pardasi bilan ochiladi', () => {
    expect(CAMERA_LOAD_MS).toBe(5_000);
    // Parda birinchi kadr bilan ochiladi (kamida MIN), kadr kelmasa — MAX da.
    expect(coverDone(300, true)).toBe(false);
    expect(coverDone(CAMERA_LOAD_MIN_MS, true)).toBe(true);
    expect(coverDone(3_000, false)).toBe(false);
    expect(coverDone(CAMERA_LOAD_MS, false)).toBe(true);
    expect([2160, 1440, 1080, 720, 432, 0].map(resolutionLabel)).toEqual(['4K', '2K', 'FHD', '720p', '432p', null]);
  });
});

describe('guruh sanoqlari va filtr', () => {
  const students = [
    student('a', 'keldi'),
    student('b', 'kech_keldi'),
    student('c', 'kelmadi'),
    student('d', 'kutilmoqda'),
    student('e', 'malumot_yoq', false),
  ];

  it('sanoq va filtr bir xil qoidada', () => {
    const seen = new Set(['a']);
    const counts = Object.fromEntries(groupCounters(students, seen).map((c) => [c.key, c.value]));
    expect(counts).toEqual({ hammasi: 5, kelgan: 2, kech_keldi: 1, kelmadi: 1, kutilmoqda: 1, yuzsiz: 1, darsda: 1, darsda_emas: 4 });
    // "Ma'lumot yo'q" kartasi olib tashlangan (2026-10-06) — qatorda yo'q.
    expect(groupCounters(students, null).map((c) => c.key)).not.toContain('malumot_yoq');
    // Yuzsiz — faqat "Yuzsiz"da (HEMIS bo'yicha kelgan bo'lsa ham).
    expect(studentMatches(student('g', 'keldi', false), 'kelgan', null)).toBe(false);
    expect(studentMatches(student('g', 'keldi', false), 'yuzsiz', null)).toBe(true);
    expect(students.filter((s) => studentMatches(s, 'kelgan', seen)).map((s) => s.id)).toEqual(['a', 'b']);
    expect(students.filter((s) => studentMatches(s, 'darsda_emas', seen)).map((s) => s.id)).toEqual(['b', 'c', 'd', 'e']);
  });

  it('dars bo‘lmasa — darsda sanoqlari yo‘q', () => {
    expect(groupCounters(students, null).map((c) => c.key)).not.toContain('darsda');
  });

  it('URL dagi noto‘g‘ri holat — hammasi', () => {
    expect(parseCounter('kelmadi')).toBe('kelmadi');
    expect(parseCounter('xyz')).toBe('hammasi');
    expect(parseCounter(null)).toBe('hammasi');
  });
});

describe('guruh paneli — dars vaqti', () => {
  it('server "09:00" ko‘rinishida beradi — xatosiz chiqadi', () => {
    expect(clock('09:00')).toBe('09:00');
    expect(clock('9:05')).toBe('09:05');
    expect(clock('2026-10-06T04:30:00Z')).toBe('09:30'); // to'liq ISO — Toshkent vaqti
    expect(clock('noto‘g‘ri')).toBe('—');
    expect(clock(null)).toBe('—');
  });
});

describe('PanelBoundary', () => {
  it('panel ichidagi xato faqat shu panelni almashtiradi', () => {
    const Broken = () => {
      throw new RangeError('Invalid time value');
    };
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <div>
        <PanelBoundary title="Guruh">
          <Broken />
        </PanelBoundary>
        <p>Qo‘shni panel</p>
      </div>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid time value');
    expect(screen.getByText('Qo‘shni panel')).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe('Bugun / Kecha — qo‘shni kun', () => {
  it('bugun <-> kecha; boshqa kunlar oldindan yuklanmaydi', () => {
    expect(neighbourDay('2026-10-06', '2026-10-06')).toBe('2026-10-05');
    expect(neighbourDay('2026-10-05', '2026-10-06')).toBe('2026-10-06');
    expect(neighbourDay('2026-10-01', '2026-10-06')).toBeNull();
  });
});

describe('Kriteriyalar bo‘yicha — guruhlar jadvali', () => {
  it('saralash: muammolisi tepada, "8/12" — 8, "—" eng pastda', () => {
    expect(sumSortValue({ value: '3', tone: 'danger' })).toBeGreaterThan(sumSortValue({ value: '9', tone: 'warning' }));
    expect(sumSortValue({ value: '8/12', tone: 'warning' })).toBe(200_008);
    expect(sumSortValue({ value: '—', tone: 'neutral' })).toBe(-1);
    expect(sumSortValue(undefined)).toBe(-1);
  });

  it('har guruh qatori va har kriteriya ustuni; qator bosilsa guruh ochiladi', async () => {
    const opened: string[] = [];
    const data = {
      period: { from: '2026-10-06', to: '2026-10-06', days: 1 },
      analysed: false,
      criteria: [
        { key: 'davomat', code: 7, label: 'Kelgan-kelmagani', description: '' },
        { key: 'chekish', code: 15, label: 'Chekkanlar', description: '' },
      ],
      groups: [
        { name: 'TPI-126', course: 1, total: 23, enrolled: 12, cells: { davomat: { value: '8/12', tone: 'warning' as const }, chekish: { value: '—', tone: 'neutral' as const } } },
      ],
    };
    render(<GroupsCriteriaTable data={data} rows={data.groups} loading={false} error={null} onOpen={(name) => opened.push(name)} />);
    expect(screen.getAllByText('Davomat').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Chekish').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ro‘yxatdan o‘tgan').length).toBeGreaterThan(0);
    screen.getAllByText('8/12')[0].click();
    expect(opened).toEqual(['TPI-126']);
  });
});
