import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { CourseBlock, Counts, FacultyDetail, GroupStat } from '../../lib/situationApi';

const counts = (over: Partial<Counts> = {}): Counts => ({
  total: 10, enrolled: 10, present: 5, late: 1, absent: 3, dayOff: 0, notYet: 2, noData: 0, rate: 50, ...over,
});

const group = (name: string, rate: number, over: Partial<Counts> = {}): GroupStat => ({
  ...counts({ rate, ...over }), name, facultyId: 'f1', faculty: 'Davolash ishi', course: 1, curator: null,
});

// Nom bo'yicha A→C, lekin foiz bo'yicha C→A: saralash ishlayotganini ko'rsatadi.
const groups = [group('DI-2301', 30), group('DI-2302', 90), group('DI-2303', 60)];
const course: CourseBlock = { course: 1, label: '1-kurs', groups, totals: counts({ total: 30, enrolled: 30 }) };

let detail: FacultyDetail = {
  id: 'f1', name: 'Davolash ishi', date: '2026-09-20', isToday: true,
  totals: counts({ total: 30, enrolled: 30 }), courses: [course],
};

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return { ...original, getFaculty: vi.fn(async () => detail), getGroups: vi.fn(async () => []) };
});
vi.mock('../../components/students/EnrollmentCampaign', () => ({
  EnrollmentCampaign: () => <div data-testid="kampaniya" />,
}));

import FacultyPage from './FacultyPage';

function renderPage(initial = '/talabalar/fakultet/f1') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/talabalar/fakultet/:facultyId" element={<FacultyPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Jadval sarlavhasidagi saralash tugmasi. */
function sortHeader(name: RegExp) {
  const table = screen.getByRole('table', { name: 'Guruhlar' });
  return within(within(table).getByRole('columnheader', { name })).getByRole('button');
}

/** Jadvaldagi guruh nomlari — ko'ringan tartibda. Birinchi ikki ustun —
 *  svetofor va xizmat kodi, guruh nomi uchinchi katakda. */
function tableGroupNames(): string[] {
  const table = screen.getByRole('table', { name: 'Guruhlar' });
  const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent ?? '');
  const index = headers.findIndex((text) => /Guruh/.test(text));
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.querySelectorAll('td')[index]?.textContent ?? '');
}

describe('Fakultet sahifasi', () => {
  beforeEach(() => {
    localStorage.clear();
    detail = { id: 'f1', name: 'Davolash ishi', date: '2026-09-20', isToday: true, totals: counts({ total: 30, enrolled: 30 }), courses: [course] };
  });

  it('jadval sarlavhasini bosish qatorlarni haqiqatan qayta saralaydi', async () => {
    // Ilgari jadval `manualSort` bilan chizilardi: strelka aylanardi, lekin
    // qatorlar joyida qolardi — bosish hech narsa qilmasdi.
    localStorage.setItem('talabalar.fakultet.korinish', JSON.stringify('table'));
    renderPage();
    await waitFor(() => expect(screen.getByRole('table', { name: 'Guruhlar' })).toBeInTheDocument());
    expect(tableGroupNames()).toEqual(['DI-2301', 'DI-2302', 'DI-2303']);

    fireEvent.click(sortHeader(/^Keldi/));
    expect(tableGroupNames()).toEqual(['DI-2301', 'DI-2303', 'DI-2302']);

    fireEvent.click(sortHeader(/^Keldi/));
    expect(tableGroupNames()).toEqual(['DI-2302', 'DI-2303', 'DI-2301']);
  });

  it("talabasi yo'q fakultet «Yuz topshirish» bilan ochilmaydi", async () => {
    // enrolledPct(0/0) = null → hasAttendanceData false edi, shuning uchun
    // bo'sh fakultet kampaniya ko'rinishida (u esa hech narsa chizmasdi) ochilardi.
    detail = {
      id: 'f1', name: 'Yangi fakultet', date: '2026-09-20', isToday: true,
      totals: counts({ total: 0, enrolled: 0, present: 0, late: 0, absent: 0, notYet: 0, rate: null }),
      courses: [],
    };
    renderPage();
    await waitFor(() => expect(screen.getByText("Guruh yo'q")).toBeInTheDocument());
    expect(screen.queryByTestId('kampaniya')).not.toBeInTheDocument();
  });

  it('kurs sarlavhasidagi jami qidiruvdan keyin ko\'rinayotgan guruhlarga mos keladi', async () => {
    // Ilgari "N guruh" qidiruvdan keyingi sondan, "M talaba · davomat X%"
    // esa butun kursdan olinardi — bitta qatorda ikki xil to'plam.
    renderPage();
    await waitFor(() => expect(screen.getByText(/3 guruh · 30 talaba/)).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText('Guruh nomi…'), { target: { value: 'DI-2302' } });
    await waitFor(() => expect(screen.getByText(/1 guruh/)).toBeInTheDocument());
    const header = screen.getByText(/1 guruh/);
    expect(header.textContent).toContain('10 talaba');
    expect(header.textContent).not.toContain('30 talaba');
  });

  it("qidiruv URL'dan o'qiladi — chuqur havola bir xil ro'yxatni beradi", async () => {
    // Ilgari qidiruv faqat komponent holatida edi: havolani ulashganda yoki
    // sahifani yangilaganda ro'yxat to'liq holatga qaytib ketardi.
    renderPage('/talabalar/fakultet/f1?qidiruv=DI-2302');
    await waitFor(() => expect(screen.getByText('DI-2302')).toBeInTheDocument());
    expect(screen.queryByText('DI-2301')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Guruh nomi…')).toHaveValue('DI-2302');
  });

  it("qidiruv faol bo'lganda umumiy karta ham topilgan guruhlardan hisoblanadi", async () => {
    // Ilgari halqa butun fakultetni (30 talaba) ko'rsatib turardi, pastda esa
    // bitta guruh — bitta ekranda ikki xil to'plam.
    renderPage();
    await waitFor(() => expect(screen.getByText(/Fakultet bo'yicha/)).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText('Guruh nomi…'), { target: { value: 'DI-2302' } });
    await waitFor(() => expect(screen.getByText(/Topilgan guruhlar bo'yicha/)).toBeInTheDocument());
    // Bitta guruh: 5 kelgan / (5 + 3 + 2) kutilgan. Qamrov nomi endi
    // panel sarlavhasi, maxraj esa uning ostidagi qator — ikkalasi ham
    // ko'rinishi kerak.
    expect(screen.getAllByText('5 / 10 keldi').length).toBeGreaterThan(0);
  });

  it("o'tgan sanada «Hali kelmagan» o'rniga «Ma'lumot yo'q» ko'rsatiladi", async () => {
    // Sahifa izohi qisqartirildi, lekin ko'rilayotgan kun AJRATILIB turishi
    // kerak: o'tgan kunda «hali kelmagan» degan holat bo'lmaydi.
    renderPage('/talabalar/fakultet/f1?sana=2020-05-04');
    await waitFor(() => expect(screen.getByText('Davolash ishi')).toBeInTheDocument());
    expect(screen.queryByText('Hali kelmagan')).not.toBeInTheDocument();
  });
});
