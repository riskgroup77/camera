import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const { board } = vi.hoisted(() => ({
  board: {
    day: '2026-09-28',
    now: true,
    items: [
      {
        id: 'l1', start: '2026-09-28T08:00:00+05:00', end: '2026-09-28T09:20:00+05:00', group: 'DI-2301',
        subject: 'Anatomiya', faculty: 'F', teacher: 'Karimov A.', teacherId: 't1', auditorium: '5-xona',
        building: '3-Oʻquv bino', cameraId: 'c1', cameraName: '5-xona', teacherStatus: 'kelmagan',
        studentsExpected: 25, studentsArrived: 20, studentsInRoom: 12,
      },
    ],
  },
}));

vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return { ...original, api: { ...original.api, get: vi.fn().mockResolvedValue(board) } };
});
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't' }) }));

import ScheduleBoard, { clock } from './ScheduleBoard';

describe('ScheduleBoard', () => {
  it("o'qituvchi holati, xona va talabalar sonini ko'rsatadi", async () => {
    render(<ScheduleBoard />);
    expect((await screen.findAllByText('DI-2301')).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Kamera ko'rmadi").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/20\/25 keldi/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/xonada ko'rindi: 12/).length).toBeGreaterThan(0);
  });

  it('vaqtni Toshkent soatida ko‘rsatadi', () => {
    expect(clock('2026-09-28T03:00:00Z')).toBe('08:00');
    expect(clock(null)).toBe('—');
  });
});
