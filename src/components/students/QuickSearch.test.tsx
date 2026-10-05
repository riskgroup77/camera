import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { GroupStat } from '../../lib/situationApi';

const group = (name: string): GroupStat => ({
  name, facultyId: null, faculty: null, course: 1, curator: null,
  total: 10, enrolled: 10, present: 5, late: 0, absent: 5, dayOff: 0, notYet: 0, noData: 0, rate: 50,
});

const getGroups = vi.fn(async () => [group('DI-2301'), group('DI-2302')]);
const post = vi.fn(async () => ({ items: [], total: 0, page: 1, pageSize: 6, totalPages: 0 }));

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return { ...original, getGroups: (...args: unknown[]) => getGroups(...(args as [])) };
});
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return { ...original, api: { ...original.api, post: (...args: unknown[]) => post(...(args as [])) } };
});

import { QuickSearch } from './QuickSearch';

function renderSearch() {
  return render(
    <MemoryRouter>
      <QuickSearch date="2026-09-20" withDate={(path) => path} />
    </MemoryRouter>,
  );
}

const box = () => screen.getByRole('combobox');

describe('QuickSearch', () => {
  beforeEach(() => {
    getGroups.mockReset().mockResolvedValue([group('DI-2301'), group('DI-2302')]);
    post.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 6, totalPages: 0 });
  });

  it('yopiq ro\'yxatda birinchi ArrowDown BIRINCHI natijani belgilaydi', async () => {
    // Ilgari u 0 dan 1 ga o'tib, birinchi guruhni o'tkazib yuborardi.
    renderSearch();
    fireEvent.change(box(), { target: { value: 'DI' } });
    await waitFor(() => expect(screen.getByRole('listbox')).toBeInTheDocument(), { timeout: 3000 });

    fireEvent.keyDown(box(), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    fireEvent.keyDown(box(), { key: 'ArrowDown' });
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(options[1]).toHaveAttribute('aria-selected', 'false');
  });

  it("ikkala so'rov ham yiqilsa — «topilmadi» emas, xato ko'rsatiladi", async () => {
    getGroups.mockRejectedValue(new Error('tarmoq'));
    post.mockRejectedValue(new Error('tarmoq'));
    renderSearch();
    fireEvent.change(box(), { target: { value: 'DI' } });
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole('alert')).toHaveTextContent(/bajarib bo'lmadi/);
    expect(screen.queryByText(/topilmadi/)).not.toBeInTheDocument();
  });

  it("natija yo'q bo'lsa — topilmadi xabari (xato emas)", async () => {
    getGroups.mockResolvedValue([]);
    renderSearch();
    fireEvent.change(box(), { target: { value: 'ZZ' } });
    await waitFor(() => expect(screen.getByText(/topilmadi/)).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
