import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactNode } from 'react';

vi.mock('./config', () => ({
  isBackendConfigured: true,
  config: { apiBaseUrl: 'https://api.test', realtimeUrl: 'wss://api.test/ws/events', streamGatewayUrl: '' },
}));

const { useLiveEvents, reconnectDelay, RECONNECT_MAX_MS } = await import('./realtime');
const { AuthProvider } = await import('./auth');

class FakeSocket {
  static instances: FakeSocket[] = [];
  static closed = 0;
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  close() {
    FakeSocket.closed += 1;
  }
}

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AuthProvider, null, children);
}

/**
 * Server qayta ishga tushganda nima bo'ladi.
 *
 * Ilgari uzilgan ulanish har 3 soniyada QAT'IY bir xil vaqtda qayta
 * urinardi. Devor ekrani, laboratoriyadagi noutbuklar va telefonlar kun
 * bo'yi ochiq turadi: server bir necha daqiqa o'chsa, u ko'tarilgan
 * zahoti o'nlab mijoz bir vaqtning o'zida, sekundiga bir necha marta
 * ulanishga urinib, endigina ko'tarilgan serverni yana bosardi. Va
 * ekranda hech narsa ko'rinmasdi: operator ro'yxat jonli deb o'ylab
 * turaverardi, aslida esa u muzlab qolgan edi.
 */
describe('jonli ulanish: qayta urinish siyosati', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    FakeSocket.closed = 0;
    vi.stubGlobal('WebSocket', FakeSocket);
    localStorage.setItem('camera-auth', JSON.stringify({ role: 'admin', userName: 'Operator', token: 'jwt' }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('kutish vaqti ikki barobardan oshib boradi va chegaradan chiqmaydi', () => {
    // Tasodifiy qo'shimchasiz (random = 0.5 => aniq baza).
    expect(reconnectDelay(1, () => 0.5)).toBe(1_000);
    expect(reconnectDelay(2, () => 0.5)).toBe(2_000);
    expect(reconnectDelay(3, () => 0.5)).toBe(4_000);
    expect(reconnectDelay(10, () => 0.5)).toBe(RECONNECT_MAX_MS);
    expect(reconnectDelay(99, () => 0.5)).toBe(RECONNECT_MAX_MS);
    // Tasodifiy qo'shimcha bor — hamma ekran bir vaqtda urinmaydi.
    expect(reconnectDelay(3, () => 0)).not.toBe(reconnectDelay(3, () => 1));
  });

  it("uzoq uzilishda urinishlar orasi kengayadi — 3 soniyalik 'bo'ron' emas", () => {
    const { result } = renderHook(() => useLiveEvents(() => {}), { wrapper });
    expect(FakeSocket.instances).toHaveLength(1);

    // Birinchi uzilish — tez qayta urinish (operator sezmasin).
    act(() => FakeSocket.instances[0].onclose?.({ code: 1006 }));
    expect(result.current).toBe('connecting');
    act(() => void vi.advanceTimersByTime(1_500));
    expect(FakeSocket.instances).toHaveLength(2);

    // Keyingi uzilishlar — kutish o'sadi: 3 soniya endi yetmaydi.
    act(() => FakeSocket.instances[1].onclose?.({ code: 1006 }));
    act(() => void vi.advanceTimersByTime(2_600));
    expect(FakeSocket.instances).toHaveLength(3);
    act(() => FakeSocket.instances[2].onclose?.({ code: 1006 }));
    act(() => void vi.advanceTimersByTime(3_000));
    expect(FakeSocket.instances).toHaveLength(3);
    act(() => void vi.advanceTimersByTime(3_000));
    expect(FakeSocket.instances).toHaveLength(4);
  });

  it('ulanish tiklangach kutish vaqti yana boshidan hisoblanadi', () => {
    renderHook(() => useLiveEvents(() => {}), { wrapper });
    act(() => FakeSocket.instances[0].onclose?.({ code: 1006 }));
    act(() => void vi.advanceTimersByTime(1_500));
    act(() => FakeSocket.instances[1].onclose?.({ code: 1006 }));
    act(() => void vi.advanceTimersByTime(3_000));
    expect(FakeSocket.instances).toHaveLength(3);

    act(() => FakeSocket.instances[2].onopen?.());
    act(() => FakeSocket.instances[2].onclose?.({ code: 1006 }));
    act(() => void vi.advanceTimersByTime(1_500));
    expect(FakeSocket.instances).toHaveLength(4);
  });

  it('holatni beradi: ulangan — live, uzilgan — connecting, rad etilgan — paused', () => {
    const { result } = renderHook(() => useLiveEvents(() => {}), { wrapper });
    expect(result.current).toBe('connecting');

    act(() => FakeSocket.instances[0].onopen?.());
    expect(result.current).toBe('live');

    act(() => FakeSocket.instances[0].onclose?.({ code: 1006 }));
    expect(result.current).toBe('connecting');

    act(() => void vi.advanceTimersByTime(1_500));
    act(() => FakeSocket.instances[1].onclose?.({ code: 4403 }));
    expect(result.current).toBe('paused');
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("yopilgan ulanishning onclose'i yangi urinish qo'ymaydi", () => {
    const { unmount } = renderHook(() => useLiveEvents(() => {}), { wrapper });
    const socket = FakeSocket.instances[0];
    unmount();
    // Brauzer close()'dan keyin ham onclose'ni chaqiradi — endi u bo'sh.
    expect(socket.onclose).toBeNull();
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
