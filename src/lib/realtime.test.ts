import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactNode } from 'react';

vi.mock('./config', () => ({
  isBackendConfigured: true,
  config: { apiBaseUrl: 'https://api.test', realtimeUrl: 'wss://api.test/ws/events', streamGatewayUrl: '' },
}));

const { useLiveEvents } = await import('./realtime');
const { AuthProvider } = await import('./auth');

class FakeSocket {
  static instances: FakeSocket[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  close() {}
}

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AuthProvider, null, children);
}

describe('useLiveEvents reconnect policy', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeSocket);
    localStorage.setItem('camera-auth', JSON.stringify({ role: 'admin', userName: 'Operator', token: 'jwt' }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('reconnects after an ordinary disconnect', () => {
    renderHook(() => useLiveEvents(() => {}), { wrapper });
    expect(FakeSocket.instances).toHaveLength(1);

    FakeSocket.instances[0].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(3_000);
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it.each([4401, 4403])('stops when the server rejects the socket (%i)', (code) => {
    renderHook(() => useLiveEvents(() => {}), { wrapper });

    FakeSocket.instances[0].onclose?.({ code });
    vi.advanceTimersByTime(30_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('does not connect at all when disabled', () => {
    renderHook(() => useLiveEvents(() => {}, false), { wrapper });
    expect(FakeSocket.instances).toHaveLength(0);
  });
});
