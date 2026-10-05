import { renderHook, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactNode } from 'react';

vi.mock('./config', () => ({
  isBackendConfigured: true,
  config: { apiBaseUrl: 'https://api.test', realtimeUrl: '', streamGatewayUrl: '' },
}));

const { useServerPage, invalidateServerPageCache } = await import('./useServerPage');
const { AuthProvider } = await import('./auth');

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AuthProvider, null, children);
}

/** Har so'rovda joriy `total` bo'yicha to'g'ri sahifani qaytaradigan soxta server. */
function fakeApi(getTotal: () => number, pageSize = 20) {
  return vi.fn(async (url: string) => {
    const page = Number(new URL(url).searchParams.get('page') ?? 1);
    const total = getTotal();
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const start = (page - 1) * pageSize;
    const items = Array.from({ length: Math.max(0, Math.min(pageSize, total - start)) }, (_, i) => ({
      id: String(start + i),
    }));
    return new Response(JSON.stringify({ items, total, page, pageSize, totalPages }), { status: 200 });
  });
}

/**
 * Sahifalash chegarasi.
 *
 * 4300 ta hodisadan 2680 tasi birdan yopilganda (yoki boshqa operator
 * navbatni tozalaganda) ro'yxat keskin qisqaradi. Operator o'sha paytda
 * chuqur sahifada turgan bo'lsa, server bo'sh ro'yxat qaytarardi va
 * ekranda "hech narsa topilmadi" turardi — yozuvlar bor bo'lsa ham.
 */
describe('useServerPage sahifa chegarasi', () => {
  beforeEach(() => {
    localStorage.setItem('camera-auth', JSON.stringify({ role: 'admin', userName: 'Operator', token: 'jwt' }));
    invalidateServerPageCache('/api/events');
  });

  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("ro'yxat qisqarganda oxirgi mavjud sahifaga qaytaradi", async () => {
    let total = 4300;
    vi.stubGlobal('fetch', fakeApi(() => total));

    const { result } = renderHook(() => useServerPage<{ id: string }>('/api/events', {}, 20), { wrapper });
    await waitFor(() => expect(result.current.items).toHaveLength(20));

    act(() => result.current.setPage(40));
    await waitFor(() => expect(result.current.page).toBe(40));
    await waitFor(() => expect(result.current.items).toHaveLength(20));

    // Filtr toraydi / hamkasb hodisalarni yopadi — 400 ta qoldi (20 sahifa).
    total = 400;
    act(() => result.current.reload());

    await waitFor(() => expect(result.current.totalPages).toBe(20));
    await waitFor(() => expect(result.current.page).toBe(20));
    // Eng muhimi: ekran bo'sh QOLMAYDI.
    await waitFor(() => expect(result.current.items.length).toBeGreaterThan(0));
  });

  it("haqiqatan bo'sh natijada sahifa 1 da qoladi (cheksiz aylanish yo'q)", async () => {
    vi.stubGlobal('fetch', fakeApi(() => 0));
    const { result } = renderHook(() => useServerPage<{ id: string }>('/api/events', {}, 20), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.page).toBe(1);
    expect(result.current.items).toHaveLength(0);
  });
});
