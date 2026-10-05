// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { KafedraStat } from '../../lib/situationApi';
import type { Loader } from './useLoader';

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return { ...original, getAnalyticsUnits: vi.fn(async () => []), getLessons: vi.fn(async () => ({ items: [], total: 0, page: 1, pageSize: 500, totalPages: 1, date: '2026-09-20', counts: { upcoming: 0, ongoing: 0, finished: 0 } })) };
});
// Qidiruv auth/permissions provayderlarini talab qiladi — bu testda kerak emas.
vi.mock('./TeacherSearch', () => ({ TeacherSearch: () => null }));

import { UnitsTab } from './UnitsTab';

beforeEach(() => localStorage.clear());

function unit(partial: Partial<KafedraStat>): KafedraStat {
  return {
    id: 'u1',
    name: 'Normal anatomiya kafedrasi',
    kind: 'kafedra',
    building: null,
    unassigned: false,
    staffTotal: 0,
    enrolled: 0,
    present: 0,
    late: 0,
    absent: 0,
    dayOff: 0,
    notYet: 0,
    noData: 0,
    rate: null,
    lessonsToday: 0,
    teacherLateLessons: 0,
    teacherMissedLessons: 0,
    ...partial,
  };
}

function loaderFor(rows: KafedraStat[]): Loader<KafedraStat[]> {
  return { data: rows, loading: false, refreshing: false, error: null, reload: () => {} };
}

function renderTab(rows: KafedraStat[], isToday = true, entry = '/oqituvchilar') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <UnitsTab loader={loaderFor(rows)} date="2026-09-20" isToday={isToday} withDate={(path) => path} />
    </MemoryRouter>,
  );
}

describe("UnitsTab — «Xodimlar keldi» plitkasi", () => {
  // 20 xodimdan 8 tasining yuzi ro'yxatdan o'tmagan: backend foizi
  // 10 / (10 + 2) = 83,3%, "jami 20 xodimning 50%" EMAS. Plitka avval
  // present/staffTotal ni hisoblab, har bir karta halqasidan boshqa foiz
  // ko'rsatardi.
  it('uses the same denominator as the unit cards and names it', async () => {
    renderTab([unit({ staffTotal: 20, enrolled: 12, present: 10, late: 2, absent: 2, noData: 8, rate: 83.3 })]);
    // Izohdagi yagona son foizning MAXRAJI bo'lishi kerak: jami xodim (20)
    // u yerda turса, plitka o'z foizidan boshqa asosni nomlagan bo'lardi.
    const hint = await screen.findByText(/Yuzi bazada bor/);
    expect(hint.textContent).toContain('Yuzi bazada bor 12 xodimdan');
    expect(hint.textContent).not.toContain('20');
  });

  it('counts people who have not arrived yet, not the ones with no face enrolled', async () => {
    renderTab([unit({ staffTotal: 10, enrolled: 9, present: 4, absent: 1, notYet: 4, noData: 1, rate: 44.4 })]);
    const hint = await screen.findByText(/Yuzi bazada bor/);
    expect(hint.textContent).toContain('Yuzi bazada bor 9 xodimdan');
  });

  // Katta sondagi maxraj "/ 20" (jami xodim) edi, yonidagi progress esa
  // 83,3% (10 / 12) — bitta plitkada ikki xil maxraj.
  it('shows the fraction over the same denominator as the percentage', async () => {
    renderTab([unit({ staffTotal: 20, enrolled: 12, present: 10, late: 2, absent: 2, noData: 8, rate: 83.3 })]);
    await screen.findByText(/Yuzi bazada bor/);
    expect(screen.getByText('/ 12')).toBeTruthy();
    expect(screen.queryByText('/ 20')).toBeNull();
  });
});

describe("UnitsTab — o'tgan sanada «Bugun» deyilmaydi", () => {
  // ?sana= bilan o'tgan kunga o'tilganda jadval sarlavhalari baribir
  // "Bugun" derdi, garchi raqamlar o'sha kunniki bo'lsa ham.
  it('labels the table columns with the viewed day', async () => {
    localStorage.setItem('oqituvchilar.view', JSON.stringify('table'));
    renderTab([unit({ staffTotal: 10, enrolled: 10, present: 8, absent: 2, rate: 80, lessonsToday: 3 })], false);
    await waitFor(() => expect(screen.getByRole('columnheader', { name: /Shu kuni ishga kelgani/ })).toBeTruthy());
    expect(screen.getByRole('columnheader', { name: /Shu kungi darslar/ })).toBeTruthy();
    expect(screen.queryByRole('columnheader', { name: /Bugun/ })).toBeNull();
  });
});

describe('UnitsTab — bo\'linma yorlig\'i', () => {
  // Bo'linma sahifasi bu qatorni "Biriktirilmagan" deb ataydi; ro'yxat
  // "Lavozim" derdi — bitta bo'linma ikki xil nomlanardi.
  it('labels the unassigned pseudo-unit the same way as its own page', async () => {
    localStorage.setItem('oqituvchilar.view', JSON.stringify('table'));
    renderTab([unit({ id: 'unassigned', name: "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)", kind: 'lavozim', unassigned: true, staffTotal: 139, present: 100, absent: 39, rate: 71.9 })]);
    await waitFor(() => expect(screen.getAllByText('Biriktirilmagan').length).toBeGreaterThan(0));
    expect(screen.queryByText('Lavozim')).toBeNull();
  });
});

describe("UnitsTab — bo'linma turi filtri URL da", () => {
  // Filtr ilgari localStorage da edi: havolani ulashgan odam "Kafedralar"
  // ni ko'rib tursa ham, qabul qiluvchi o'z brauzeridagi eski tanlovni
  // ko'rardi — ikkalasi boshqa-boshqa ro'yxat ustida gaplashardi.
  it('applies ?tur= from the link', async () => {
    const rows = [
      unit({ id: 'k1', name: 'Anatomiya kafedrasi', kind: 'kafedra' }),
      unit({ id: 'd1', name: 'Davolash dekanati', kind: 'dekanat' }),
    ];
    renderTab(rows, true, '/oqituvchilar?tur=dekanat');
    await waitFor(() => expect(screen.getByText('Davolash dekanati')).toBeTruthy());
    expect(screen.queryByText('Anatomiya kafedrasi')).toBeNull();
  });

  it('falls back to all units for an unknown ?tur=', async () => {
    const rows = [unit({ id: 'k1', name: 'Anatomiya kafedrasi', kind: 'kafedra' })];
    renderTab(rows, true, '/oqituvchilar?tur=yoq-narsa');
    await waitFor(() => expect(screen.getByText('Anatomiya kafedrasi')).toBeTruthy());
  });
});

describe('UnitsTab — taxtadagi raqamlar foiz maxraji bilan mos', () => {
  /** Taxta katagidagi ikkinchi qator — foizning izohi. */
  function boardDetail(): string {
    return screen.getByTitle(/Normal anatomiya kafedrasi —/).textContent ?? '';
  }

  // "Hali kelmagan" xodimlar ro'yxatda umuman ko'rinmasdi: uch raqam
  // qo'shilib foiz maxrajiga teng chiqmasdi va sababi topilmasdi.
  it('shows the people who have not arrived yet, inside the same denominator', async () => {
    renderTab([unit({ staffTotal: 10, enrolled: 9, present: 4, late: 1, absent: 1, notYet: 4, noData: 1, rate: 44.4 })]);
    await waitFor(() => expect(screen.getByText('Normal anatomiya kafedrasi')).toBeTruthy());
    // 4 + 1 + 4 = 9 — foiz maxraji; "hali kelmagan" ham alohida aytiladi.
    expect(boardDetail()).toContain('4 / 9 keldi');
    expect(boardDetail()).toContain('4 hali kelmagan');
  });

  it('says nothing about pending people when there are none', async () => {
    renderTab([unit({ staffTotal: 10, enrolled: 10, present: 8, late: 1, absent: 2, notYet: 0, rate: 80 })]);
    await waitFor(() => expect(screen.getByText('Normal anatomiya kafedrasi')).toBeTruthy());
    expect(boardDetail()).toContain('8 / 10 keldi');
    expect(boardDetail()).not.toContain('hali kelmagan');
  });
});
