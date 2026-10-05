import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { CalendarDay, PersonProfile } from '../../lib/situationApi';
import type { AttendanceSummary } from '../../types';

// Sana QOTIRILMAYDI: ilgari bu yerda '2026-09-20' turardi va o'sha kun
// o'tishi bilan "kelajakdagi oraliq" testi yiqildi. Soat ham bir joyga
// qotiriladi — yarim tunda o'tayotgan test ishonchsiz bo'ladi.
vi.useFakeTimers({ toFake: ['Date'] });
vi.setSystemTime(new Date('2026-09-20T09:00:00+05:00'));
const TODAY = '2026-09-20';

const day = (date: string, status: CalendarDay['status'], checkIn: string | null = null): CalendarDay => ({
  date, status, checkIn, checkOut: null,
});

// 30 kunlik davr: 3 kun keldi (1 kech), 1 kun kelmadi, qolgani yozuvsiz.
const calendar: CalendarDay[] = [
  day('2026-09-14', 'keldi', '08:00'),
  day('2026-09-15', 'kech_keldi', '09:10'),
  day('2026-09-16', 'kelmadi'),
  day('2026-09-17', 'keldi', '08:05'),
  ...Array.from({ length: 26 }, (_, i) => day(`2026-08-${String(i + 10).padStart(2, '0')}`, 'malumot_yoq')),
];

const profile: PersonProfile = {
  person: {
    id: 'p1', fullName: 'Aliyev Anvar', type: 'talaba', photoUrl: null, initials: 'AA',
    facultyId: 'f1', faculty: 'Davolash ishi', unit: '1-kurs, DI-2301', group: 'DI-2301', course: 1,
    departmentId: null, department: null, biometricsStatus: 'tasdiqlangan', parentNotify: false, active: true,
  },
  dateFrom: '2026-09-01',
  dateTo: TODAY,
  calendar,
  totals: { days: 30, present: 3, late: 1, absent: 1, dayOff: 0, noData: 26, rate: 75, avgArrival: '08:25' },
  lessons: [],
  recentVisits: [],
};

const summary: AttendanceSummary = {
  person: {
    id: 'p1', fullName: 'Aliyev Anvar', type: 'talaba', faculty: 'Davolash ishi', unit: 'DI-2301',
    biometricsStatus: 'tasdiqlangan', initials: 'AA', biometricPhotoUrl: null,
  },
  months: [],
  workingWeekdays: [1, 2, 3, 4, 5, 6],
};

const getPerson = vi.fn(async () => profile);
vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return { ...original, getPerson: (...args: unknown[]) => getPerson(...(args as [])) };
});
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return {
    ...original,
    api: {
      ...original.api,
      get: vi.fn(async (path: string) => (path.includes('/summary') ? summary : [])),
    },
  };
});
vi.mock('../../lib/attendancePolicyApi', () => ({
  getAttendancePolicy: vi.fn(async () => ({ studentLateAfter: '08:10', staffLateAfter: '08:10' })),
}));
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ role: 'admin', token: 't', userName: null }) }));
vi.mock('../../lib/permissions', () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock('../../lib/realtime', () => ({ useLiveAttendance: () => {} }));
vi.mock('../../components/attendance/DayDrawer', () => ({ default: () => null }));
vi.mock('../../components/students/GroupEnrollDrawer', () => ({ GroupEnrollDrawer: () => null }));

import PersonPage from './PersonPage';

function renderPage(initial = '/shaxs/p1') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/shaxs/:personId" element={<PersonPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Shaxs sahifasi — davomat ko\'rsatkichlari', () => {
  it('"Kelgan kunlari ulushi" izohi foizning haqiqiy asosini ko\'rsatadi', async () => {
    // Ilgari izoh "Tanlangan davrdagi 30 ish kunidan" derdi: 30 — davrdagi
    // BARCHA kunlar (dam olish va yozuvsiz kunlar bilan), foiz esa
    // kelgan/(kelgan+kelmagan) = 3/4 dan chiqardi.
    renderPage();
    await waitFor(() => expect(screen.getByText('Aliyev Anvar')).toBeInTheDocument());
    expect(screen.getByText('Kelgan kunlari ulushi')).toBeInTheDocument();
    expect(screen.getByText('Yozuv bor 4 kundan 3 tasida kelgan')).toBeInTheDocument();
    expect(screen.queryByText(/30 ish kunidan/)).not.toBeInTheDocument();
  });

  it("o'z vaqtida / kech / kelmagan kunlar bir-birini takrorlamaydi", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("O'z vaqtida kelgan")).toBeInTheDocument());
    // present (3) kech kelganni ham o'z ichiga oladi — plitkada u ayriladi.
    expect(screen.getByText('2 kun')).toBeInTheDocument();
    expect(screen.getAllByText('1 kun')).toHaveLength(2);
  });
});

beforeEach(() => {
  getPerson.mockClear();
});

describe('Shaxs sahifasi — URL dagi davr', () => {
  // ?gacha= bugundan keyin bo'lsa u bugunga qisqartiriladi. BUTUN oraliq
  // kelajakda bo'lganda qisqartirishdan keyin from > to bo'lib qolar va
  // serverga teskari oraliq ketardi.
  it('never sends an inverted range when the whole period is in the future', async () => {
    renderPage('/shaxs/p1?dan=2026-10-01&gacha=2026-10-31');
    await waitFor(() => expect(getPerson).toHaveBeenCalled());
    const [, range] = getPerson.mock.calls[0] as unknown as [string, { from: string; to: string }];
    expect(range.from <= range.to).toBe(true);
    expect(range.to <= TODAY).toBe(true);
  });

  it('keeps a valid range from the URL', async () => {
    renderPage('/shaxs/p1?dan=2026-09-01&gacha=2026-09-10');
    await waitFor(() => expect(getPerson).toHaveBeenCalled());
    const [, range] = getPerson.mock.calls[0] as unknown as [string, { from: string; to: string }];
    expect(range).toMatchObject({ from: '2026-09-01', to: '2026-09-10' });
  });
});
