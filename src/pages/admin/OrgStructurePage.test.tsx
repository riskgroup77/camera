// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * QA: tashkiliy tuzilma sahifasi. Fakultet, guruh va kafedra HEMIS'dan
 * keladi — qo'lda o'chirilsa keyingi sinxronlashda qaytib kelardi.
 */

const del = vi.fn().mockResolvedValue(undefined);

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin' }) }));
vi.mock('../../lib/permissions', () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock('../../lib/apiClient', () => ({
  ApiError: class ApiError extends Error {},
  isAbortError: () => false,
  buildQuery: () => '',
  api: {
    del: (...args: unknown[]) => del(...args),
    get: (path: string) => {
      if (path.includes('/tuzilma')) return Promise.resolve({ date: '2026-09-26', units: [], positions: [] });
      if (path === '/api/buildings') return Promise.resolve([]);
      if (path === '/api/departments') return Promise.resolve([]);
      if (path === '/api/faculties') {
        return Promise.resolve([{ id: 'f1', name: 'Stomatologiya', courseCount: 5, studentCount: 10 }]);
      }
      return Promise.resolve([
        { id: 'g1', name: 'DI-2301', faculty: 'Stomatologiya', course: 2, studentCount: 10 },
      ]);
    },
  },
}));

import OrgStructurePage from './OrgStructurePage';

describe("OrgStructurePage — HEMIS ro'yxatlari", () => {
  it("fakultetni qo'lda o'chirib bo'lmaydi — ro'yxat HEMIS'dan keladi", async () => {
    render(
      <MemoryRouter initialEntries={['/tuzilma?tab=fakultetlar']}>
        <OrgStructurePage />
      </MemoryRouter>,
    );

    // Jadval ish stoli va telefon ko'rinishida ikki marta chiziladi.
    await waitFor(() => expect(screen.getAllByText('Stomatologiya').length).toBeGreaterThan(0));
    // HEMIS keyingi sinxronlashda qaytarib qo'yardi — o'chirish tugmasi yo'q.
    expect(screen.queryAllByLabelText("«Stomatologiya» — o'chirish")).toHaveLength(0);
    expect(screen.getByText(/HEMIS'dan avtomatik yangilanadi/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole('tab', { name: /Guruhlar/ })[0]);
    await waitFor(() => expect(screen.getAllByText('DI-2301').length).toBeGreaterThan(0));
    expect(del).not.toHaveBeenCalled();
  });
});
