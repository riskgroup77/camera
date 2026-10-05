import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { KpiReport } from '../../lib/kpiApi';
import KpiView from './KpiView';

const DATA: KpiReport = {
  period: { from: '2026-09-14', to: '2026-09-20', days: 7 },
  attendance: {
    staff: { rate: 92, prevRate: 88, latePct: 3, prevLatePct: 5, present: 10, late: 1, absent: 1, daysCovered: 5 },
    students: { rate: null, prevRate: null, latePct: null, prevLatePct: null, present: 0, late: 0, absent: 0, daysCovered: 0 },
    previous: { from: '2026-09-07', to: '2026-09-13' },
  },
  recognition: {
    studentsCoverage: 40, staffCoverage: 95, studentsEnrolled: 4, studentsTotal: 10, staffEnrolled: 19, staffTotal: 20,
    recognisedDailyPct: 81, unknownPending: 2,
  },
  security: {
    events: 3, reviewed: 2, rejected: 1, confirmed: 1, open: 1, falsePct: 50, reviewMinutes: 15, resolveMinutes: 60,
    modules: [{ code: 5, name: 'Uxlash', events: 3, reviewed: 2, rejected: 1, confirmed: 1, open: 1, falsePct: 50,
      reviewMinutes: 15, resolveMinutes: 60 }],
  },
  infrastructure: { camerasTotal: 3, camerasActive: 2, camerasOnline: 1, videoFlowing: 1, onlinePct: 50 },
};

vi.mock('../../lib/useApiResource', () => ({
  useApiResource: () => ({ data: DATA, loading: false, error: null, reload: () => {} }),
}));

describe('KpiView', () => {
  it('guruhlar, trend va modullar jadvali', () => {
    render(<KpiView from="2026-09-14" to="2026-09-20" />);
    expect(screen.getByText('92%')).toBeTruthy();
    expect(screen.getByText('+4')).toBeTruthy();
    expect(screen.getByText('Uxlash')).toBeTruthy();
    expect(screen.getAllByText('1 soat')).toHaveLength(2); // plitka + jadval
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});
