// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { KafedraDetail, KafedraTeacher } from '../../lib/situationApi';

const getKafedra = vi.fn();

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return {
    ...original,
    getKafedra: (...args: unknown[]) => getKafedra(...args),
    getLessons: vi.fn(async () => ({ items: [], total: 0, page: 1, pageSize: 500, totalPages: 1, date: '2026-09-20', counts: { upcoming: 0, ongoing: 0, finished: 0 } })),
  };
});
vi.mock('../../components/lessons/LessonDrawer', () => ({ LessonDrawer: () => null }));
vi.mock('../../components/lessons/LessonsTable', () => ({ LessonsTable: () => null }));

import KafedraPage from './KafedraPage';

function teacher(partial: Partial<KafedraTeacher> = {}): KafedraTeacher {
  return {
    id: 't1',
    fullName: "Abdurahmonov Shohruhbek Ulug'bek o'g'li",
    photoUrl: null,
    initials: 'AS',
    position: 'Katta o‘qituvchi',
    biometricsStatus: 'tasdiqlangan',
    status: 'keldi',
    checkIn: '08:02',
    checkOut: null,
    lessonsScheduled: 0,
    lessonsOnTime: 0,
    lessonsLate: 0,
    lessonsMissed: 0,
    periodLessons: 0,
    periodOnTime: 0,
    periodLate: 0,
    periodMissed: 0,
    onTimeRate: null,
    avgActivityScore: null,
    periodPresentDays: 18,
    periodLateDays: 2,
    periodAbsentDays: 1,
    ...partial,
  };
}

function detail(patch: Partial<KafedraDetail> = {}, todayPatch: Partial<KafedraDetail['today']> = {}, periodPatch: Partial<KafedraDetail['period']> = {}): KafedraDetail {
  return {
    id: 'u1',
    name: 'Normal anatomiya kafedrasi',
    kind: 'kafedra',
    building: null,
    unassigned: false,
    date: '2026-09-20',
    isToday: true,
    today: { total: 20, enrolled: 12, present: 10, late: 2, absent: 2, dayOff: 0, notYet: 0, noData: 8, rate: 83.3, ...todayPatch },
    teachers: [teacher()],
    period: {
      dateFrom: '2026-08-22',
      dateTo: '2026-09-20',
      lessons: 0,
      onTime: 0,
      late: 0,
      missed: 0,
      unknown: 0,
      onTimeRate: null,
      avgActivityScore: null,
      presentDays: 18,
      lateDays: 2,
      absentDays: 1,
      ...periodPatch,
    },
    ...patch,
  };
}

function renderPage(entry = '/oqituvchilar/kafedra/u1') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/oqituvchilar/kafedra/:departmentId" element={<KafedraPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  getKafedra.mockReset();
});

describe('KafedraPage — «Bugun ishga kelgan xodimlar» plitkasi', () => {
  // rate = present / (present + absent + notYet) — yuzi ro'yxatdan
  // o'tmaganlar (noData) foizga KIRMAYDI. Izoh esa "jami 20 xodimning
  // 83%" derdi, ya'ni raqam o'z yorlig'iga to'g'ri kelmasdi.
  it('names the real denominator of the percentage', async () => {
    getKafedra.mockResolvedValue(detail());
    renderPage();
    // Izohdagi yagona son foizning MAXRAJI: jami xodim (20) u yerda tursa,
    // plitka o'z foizidan boshqa asosni nomlagan bo'lardi.
    const hint = await screen.findByText(/Holati aniq/);
    expect(hint.textContent).toBe('Holati aniq 12 xodimdan');
    expect(hint.textContent).not.toContain('20');
  });

  // Katta son "10 / 20" edi, yonidagi progress esa 83,3% — ikki xil maxraj
  // bitta plitkada. Maxraj foiznikiga tenglashtirildi (10 / 12).
  it('shows the fraction over the same denominator as the percentage', async () => {
    getKafedra.mockResolvedValue(detail());
    renderPage();
    await screen.findByText(/Holati aniq/);
    expect(screen.getByText('/ 12')).toBeTruthy();
    expect(screen.queryByText('/ 20')).toBeNull();
  });
});

describe('KafedraPage — o\'tgan sanada "Bugun" deyilmaydi', () => {
  // ?sana= bilan o'tgan kunga o'tilganda plitkalar, ustun sarlavhasi va
  // sahifa izohi baribir "bugun" derdi — raqamlar boshqa kunniki edi.
  it('labels the tiles and the status column with the viewed day', async () => {
    localStorage.setItem('kafedra.view', JSON.stringify('table'));
    getKafedra.mockResolvedValue(detail({ isToday: false, date: '2026-09-15' }));
    renderPage('/oqituvchilar/kafedra/u1?sana=2026-09-15');
    await waitFor(() => expect(screen.getByText('Shu kuni keldi')).toBeTruthy());
    expect(screen.getByText('Shu kuni kech keldi')).toBeTruthy();
    expect(screen.queryByText(/^Bugun/)).toBeNull();
    expect(screen.getByRole('columnheader', { name: /Shu kuni/ })).toBeTruthy();
  });
});

describe('KafedraPage — dars ustuni dars jadvaliga bog\'liq', () => {
  it('hides the on-time-at-lesson column when the period has no lessons', async () => {
    localStorage.setItem('kafedra.view', JSON.stringify('table'));
    getKafedra.mockResolvedValue(detail());
    renderPage();
    await screen.findByRole('columnheader', { name: /Bugun/ });
    expect(screen.queryByRole('columnheader', { name: /Darsga o'z vaqtida/ })).toBeNull();
    expect(screen.getByRole('columnheader', { name: /Kelgan kunlari/ })).toBeTruthy();
  });

  it('shows the column again as soon as lessons exist', async () => {
    localStorage.setItem('kafedra.view', JSON.stringify('table'));
    getKafedra.mockResolvedValue(
      detail({ teachers: [teacher({ periodLessons: 12, periodOnTime: 10, periodLate: 2, onTimeRate: 83.3 })] }, {}, { lessons: 12, onTime: 10, late: 2, onTimeRate: 83.3 }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole('columnheader', { name: /Darsga o'z vaqtida/ })).toBeTruthy());
  });
});

describe('KafedraPage — havolalar ko\'rilayotgan sanani saqlaydi', () => {
  it('keeps ?sana= on the teacher profile link', async () => {
    localStorage.setItem('kafedra.view', JSON.stringify('table'));
    getKafedra.mockResolvedValue(detail());
    renderPage('/oqituvchilar/kafedra/u1?sana=2026-09-15');
    // DataTable keng ekranda jadval, tor ekranda kartochka chiqaradi —
    // ikkalasi ham bir xil havolani beradi, shuning uchun hammasi tekshiriladi.
    const links = await screen.findAllByRole('link', { name: /Abdurahmonov/ });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link.getAttribute('href')).toContain('sana=2026-09-15');
    }
  });
});

describe('KafedraPage — punktuallik davri URL da', () => {
  // Davr ilgari faqat komponent ichidagi useState edi: sahifani yangilash
  // yoki havolani ulashish tanlangan davrni yo'qotardi.
  it('takes the period from ?dan=/?gacha=', async () => {
    getKafedra.mockResolvedValue(detail());
    renderPage('/oqituvchilar/kafedra/u1?dan=2026-08-01&gacha=2026-08-31');
    await waitFor(() => expect(getKafedra).toHaveBeenCalled());
    const [, params] = getKafedra.mock.calls[0] as unknown as [string, { from: string; to: string }];
    expect(params).toMatchObject({ from: '2026-08-01', to: '2026-08-31' });
  });

  it('ignores an inverted range in the URL instead of querying it', async () => {
    getKafedra.mockResolvedValue(detail());
    renderPage('/oqituvchilar/kafedra/u1?dan=2026-08-31&gacha=2026-08-01');
    await waitFor(() => expect(getKafedra).toHaveBeenCalled());
    const [, params] = getKafedra.mock.calls[0] as unknown as [string, { from: string; to: string }];
    expect(params.from <= params.to).toBe(true);
  });
});

describe("KafedraPage — tab hisoblagichi jadvalga mos", () => {
  // Hisoblagich doim bo'linmadagi JAMI xodimni ko'rsatardi: qidiruvdan
  // keyin ro'yxatda 0 kishi qolsa ham tabda eski son turardi.
  it('counts the rows that the search actually leaves', async () => {
    getKafedra.mockResolvedValue(detail({ teachers: [teacher(), teacher({ id: 't2', fullName: 'Karimova Dilnoza' })] }));
    renderPage();
    const tab = await screen.findByRole('tab', { name: /O'qituvchilar/ });
    expect(tab.textContent).toContain('2');
    fireEvent.change(screen.getByLabelText("O'qituvchini qidirish"), { target: { value: 'Karimova' } });
    await waitFor(() => expect(screen.getByRole('tab', { name: /O'qituvchilar/ }).textContent).toContain('1'));
  });
});
