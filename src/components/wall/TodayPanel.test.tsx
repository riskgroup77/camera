import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Counts } from '../../lib/situationApi';
import type { EnrollCounts } from '../../lib/wallApi';
import { coverageNote, TodayPanel } from './TodayPanel';

const counts = (over: Partial<Counts> = {}): Counts => ({
  total: 6912,
  enrolled: 1030,
  present: 900,
  late: 60,
  absent: 80,
  dayOff: 0,
  notYet: 50,
  noData: 5882,
  rate: 87.4,
  ...over,
});

const enroll: EnrollCounts = { total: 5000, confirmed: 200, pending: 10, none: 4790, pct: 4 };

/** Institutda 6912 faol odam bor, yuzi ro'yxatdan o'tgani ~1030 ta:
 *  davomat foizi faqat shular bo'yicha o'lchanadi. Qamrovsiz "87%"
 *  rahbar uchun butun institut davomati bo'lib o'qilardi. */
describe('TodayPanel — foizning qamrovi', () => {
  it("ro'yxatdagilar va yuzi o'tganlar soni yoziladi", () => {
    const note = coverageNote(counts())?.replace(/\s/g, ' ');
    expect(note).toContain('6 912');
    expect(note).toContain('1 030');
  });

  it("hamma yuzi ro'yxatdan o'tgan bo'lsa izoh yo'q", () => {
    expect(coverageNote(counts({ total: 100, enrolled: 100 }))).toBeNull();
    expect(coverageNote(counts({ total: 0, enrolled: 0 }))).toBeNull();
  });

  it('panelda qamrov izohi ko\'rinadi', () => {
    render(
      <TodayPanel students={counts()} staff={counts()} studentsDataAvailable studentsEnroll={enroll} />,
    );
    expect(screen.getAllByText(/1 030 \/ 6 912 yuz/).length).toBeGreaterThan(0);
  });
});
