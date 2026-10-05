// @vitest-environment jsdom
import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useVisibleInterval } from './useVisibleInterval';

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('useVisibleInterval', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  });

  it("ko'rinib turganda har intervalda chaqiradi", () => {
    const fn = vi.fn();
    renderHook(() => useVisibleInterval(fn, 1000));
    expect(fn).toHaveBeenCalledTimes(0); // darhol chaqirmaydi

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("yorliq fonga o'tsa to'xtaydi, qaytganda bir marta chaqiradi", () => {
    const fn = vi.fn();
    renderHook(() => useVisibleInterval(fn, 1000));

    act(() => {
      setVisibility('hidden');
      vi.advanceTimersByTime(5000);
    });
    expect(fn).toHaveBeenCalledTimes(0);

    act(() => {
      setVisibility('visible');
    });
    expect(fn).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('delayMs null — taymer umuman ishlamaydi', () => {
    const fn = vi.fn();
    renderHook(() => useVisibleInterval(fn, null));
    act(() => {
      setVisibility('visible');
      vi.advanceTimersByTime(10_000);
    });
    expect(fn).toHaveBeenCalledTimes(0);
  });

  it('eng oxirgi callback chaqiriladi (taymer qayta qurilmaydi)', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ cb }) => useVisibleInterval(cb, 1000), {
      initialProps: { cb: first },
    });
    rerender({ cb: second });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(first).toHaveBeenCalledTimes(0);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('unmount taymerni tozalaydi', () => {
    const fn = vi.fn();
    const { unmount } = renderHook(() => useVisibleInterval(fn, 1000));
    unmount();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(fn).toHaveBeenCalledTimes(0);
  });
});
