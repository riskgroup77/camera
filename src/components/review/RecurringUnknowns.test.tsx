import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RecurringUnknown } from '../../lib/notanishlarApi';

const { item, assignRecurring } = vi.hoisted(() => {
  const item: RecurringUnknown = {
  key: 'a',
  sightingIds: ['a', 'b', 'c'],
  days: 3,
  hits: 12,
  cameras: ['Koridor', '5-xona'],
  firstSeenAt: '2026-09-22T05:00:00+00:00',
  lastSeenAt: '2026-09-24T06:30:00+00:00',
  facePx: 90,
  cropUrls: [],
  hints: [{ personId: 'p1', fullName: 'Aliyev Anvar', groupOrPosition: '101', similarity: 0.41 }],
  };
  const assignRecurring = vi.fn().mockResolvedValue({ message: 'Aliyev Anvar: yuzi tizimga kiritildi', count: 3 });
  return { item, assignRecurring };
});

vi.mock('../../lib/notanishlarApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/notanishlarApi')>();
  return {
    ...original,
    getRecurringUnknowns: vi.fn().mockResolvedValue({ items: [item], pending: 3 }),
    assignRecurring: (...args: unknown[]) => assignRecurring(...args),
    dismissRecurring: vi.fn().mockResolvedValue({ message: '', count: 3 }),
  };
});

vi.mock('../../ui', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../ui')>();
  return { ...original, useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }) };
});

import RecurringUnknowns from './RecurringUnknowns';

describe('RecurringUnknowns', () => {
  it("kunlar, kameralar va ishorani ko'rsatadi; ishora bir bosishda butun guruhni biriktiradi", async () => {
    render(<RecurringUnknowns />);
    expect(await screen.findByText('Koridor, 5-xona')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Aliyev Anvar'));
    await waitFor(() => expect(assignRecurring).toHaveBeenCalledWith(['a', 'b', 'c'], 'p1'));
    await waitFor(() => expect(screen.queryByText('Koridor, 5-xona')).not.toBeInTheDocument());
  });
});
