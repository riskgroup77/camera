import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { EnrollGroup, Enrollment } from '../../lib/situationApi';

const counts = { total: 40, confirmed: 15, pending: 0, none: 25, pct: 37.5 };

const enrollment: Enrollment = {
  students: counts,
  staff: { total: 0, confirmed: 0, pending: 0, none: 0, pct: null },
  byFaculty: [
    { ...counts, id: 'di', name: 'Davolash ishi' },
    { ...counts, id: 'pe', name: 'Pedagogika' },
  ],
  studentsDataAvailable: true,
};

const group = (name: string, facultyId: string, faculty: string, confirmed: number): EnrollGroup => ({
  name,
  facultyId,
  faculty,
  course: 2,
  total: 10,
  confirmed,
  pending: 0,
  pct: confirmed * 10,
});

// Filtrlanmagan ro'yxat: 2 ta boshlanmagan, 1 ta jarayonda, 1 ta tayyor.
const groups: EnrollGroup[] = [
  group('DI-2301', 'di', 'Davolash ishi', 0),
  group('DI-2302', 'di', 'Davolash ishi', 5),
  group('PE-2501', 'pe', 'Pedagogika', 10),
  group('PE-2502', 'pe', 'Pedagogika', 0),
];

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return {
    ...original,
    getEnrollment: vi.fn(async () => enrollment),
    getEnrollmentGroups: vi.fn(async () => groups),
  };
});
vi.mock('./GroupEnrollDrawer', () => ({ GroupEnrollDrawer: () => null }));

import { EnrollmentCampaign } from './EnrollmentCampaign';

function renderCampaign() {
  return render(
    <MemoryRouter>
      <EnrollmentCampaign today="2026-09-20" withDate={(path) => path} />
    </MemoryRouter>,
  );
}

/** Jadval ustidagi "N boshlanmagan · N jarayonda · N tayyor" qatori
 *  bo'shliqlari normallashtirilgan holda. */
const headerCounts = () => screen.getByText(/boshlanmagan/, { selector: 'p' }).textContent?.replace(/\s+/g, ' ').trim();

describe('Yuz topshirish kampaniyasi — guruhlar', () => {
  it('sarlavhadagi sonlar jadvaldagi qatorlar bilan bir xil', async () => {
    renderCampaign();
    await waitFor(() => expect(screen.getAllByText('DI-2301').length).toBeGreaterThan(0));
    expect(headerCounts()).toBe('2 boshlanmagan · 1 jarayonda · 1 tayyor');

    // Qidiruv jadvalni ikkita guruhga toraytiradi — sarlavha ham
    // o'sha ikki qatordan hisoblanishi kerak (ilgari u filtrlanmagan
    // to'liq ro'yxatni ko'rsatib, jadvalga zid chiqardi).
    fireEvent.change(screen.getByPlaceholderText('Guruh nomi…'), { target: { value: 'DI-23' } });
    await waitFor(() => expect(screen.queryAllByText('PE-2501')).toHaveLength(0));
    expect(screen.getAllByText('DI-2301').length).toBeGreaterThan(0);
    expect(screen.getAllByText('DI-2302').length).toBeGreaterThan(0);
    expect(headerCounts()).toBe('1 boshlanmagan · 1 jarayonda · 0 tayyor');
  });
});

describe("ro'yxatda yo'q fakultet doirasi", () => {
  it("bo'sh sahifa o'rniga nol ko'rsatkich chiziladi", async () => {
    // byFaculty da "Fakultetsiz" (id null) yozuv bo'lmasa counts null bo'lib,
    // komponent null qaytarardi — «Yuz topshirish» tabi butunlay bo'sh edi.
    render(
      <MemoryRouter>
        <EnrollmentCampaign facultyId="fakultetsiz" today="2026-09-20" withDate={(path) => path} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText('Yuz topshirish kampaniyasi')).toBeInTheDocument());
    expect(screen.getByText(/talabaning yuzi tasdiqlangan/)).toBeInTheDocument();
    expect(screen.getByText("Guruhlar yo'q")).toBeInTheDocument();
  });
});
