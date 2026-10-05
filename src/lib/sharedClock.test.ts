// @vitest-environment jsdom
import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetSharedClock, sharedClockListenerCount, useSharedNow } from './sharedClock';

describe('sharedClock', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  });
  afterEach(() => {
    resetSharedClock();
    vi.useRealTimers();
  });

  it("ko'p obunachiga bitta taymer", () => {
    const spy = vi.spyOn(window, 'setInterval');
    const a = renderHook(() => useSharedNow(true));
    const b = renderHook(() => useSharedNow(true));
    const c = renderHook(() => useSharedNow(true));

    expect(sharedClockListenerCount()).toBe(3);
    expect(spy).toHaveBeenCalledTimes(1);

    a.unmount();
    b.unmount();
    c.unmount();
    expect(sharedClockListenerCount()).toBe(0);
    spy.mockRestore();
  });

  it('30 soniyada yangi vaqt beradi', () => {
    const { result } = renderHook(() => useSharedNow(true));
    const first = result.current;
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(result.current).toBeGreaterThan(first);
  });

  it("enabled=false — obuna bo'lmaydi", () => {
    renderHook(() => useSharedNow(false));
    expect(sharedClockListenerCount()).toBe(0);
  });

  it("yashirin yorliqda yangilanmaydi", () => {
    const { result } = renderHook(() => useSharedNow(true));
    const first = result.current;
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(result.current).toBe(first);
  });
});
