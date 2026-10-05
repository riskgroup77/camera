// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const DEVICES = [
  {
    id: 'd1', name: 'Asosiy kirish', kind: 'hikvision', ip: '10.0.0.5', port: 80, username: 'admin', hasPassword: true,
    hasApiKey: false, direction: 'kirish', buildingId: null, buildingName: '1-bino', marksAttendance: true, enabled: true,
    status: 'onlayn', lastEventAt: null, lastPollAt: '2026-09-24T08:10:05+05:00', lastError: null, webhookPath: null, createdAt: null,
  },
  {
    id: 'd2', name: 'Oraliq dastur', kind: 'webhook', ip: null, port: null, username: null, hasPassword: false,
    hasApiKey: true, direction: 'ikkalasi', buildingId: null, buildingName: null, marksAttendance: true, enabled: true,
    status: 'xato', lastEventAt: null, lastPollAt: null, lastError: 'timeout', webhookPath: '/api/access/webhook/d2', createdAt: null,
  },
];
const EVENTS = [
  { id: 'e1', deviceId: 'd1', deviceName: 'Asosiy kirish', occurredAt: '2026-09-24T08:01:02+05:00', cardNumber: '1', employeeNo: null,
    personId: 'p1', personName: 'Aliyev Vali', personType: 'talaba', personUnit: 'DI-1', direction: 'kirish', granted: true },
  { id: 'e2', deviceId: 'd1', deviceName: 'Asosiy kirish', occurredAt: '2026-09-24T08:05:00+05:00', cardNumber: '00999', employeeNo: null,
    personId: null, personName: null, personType: null, personUnit: null, direction: 'kirish', granted: false },
];

const getMock = vi.fn(async (path: string) => {
  if (path.startsWith('/api/access/devices')) return DEVICES;
  if (path.startsWith('/api/access/summary')) return { date: '2026-09-24', total: 2, entries: 2, exits: 0, denied: 1, unmatched: 1, people: 1 };
  throw new Error(`kutilmagan so'rov: ${path}`);
});

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin', userName: 'Admin' }) }));
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return { ...original, api: { ...original.api, get: (path: string) => getMock(path) } };
});
const serverPageParams = vi.fn();
vi.mock('../../lib/useServerPage', () => ({
  invalidateServerPageCache: vi.fn(),
  useServerPage: (_path: string, params: Record<string, string | undefined>) => {
    serverPageParams(params);
    return { items: EVENTS, page: 1, setPage: vi.fn(), totalPages: 1, total: 2, pageSize: 25, loading: false, error: null, reload: vi.fn() };
  },
}));

import AccessPage from './AccessPage';

describe('AccessPage', () => {
  it("qurilmalar holati, bugungi sanoq va o'tishlar", async () => {
    render(
      <MemoryRouter initialEntries={['/turniketlar']}>
        <AccessPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getAllByText('Oraliq dastur').length).toBeGreaterThan(0));
    expect(screen.getByText('1/2 onlayn')).toBeInTheDocument();
    // Xatodagi qurilma yuqorida.
    const rows = screen.getAllByRole('row').map((row) => row.textContent ?? '');
    expect(rows.findIndex((t) => t.includes('Oraliq dastur'))).toBeLessThan(rows.findIndex((t) => t.includes('10.0.0.5')));

    expect(screen.getAllByText('Aliyev Vali').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Karta 00999').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Rad etildi').length).toBeGreaterThan(0);
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(expect.stringContaining('/api/access/summary?date=')));
    // Bitta kunlik jurnal: from = to.
    const params = serverPageParams.mock.calls[0][0];
    expect(params.from).toBe(params.to);
  });
});
