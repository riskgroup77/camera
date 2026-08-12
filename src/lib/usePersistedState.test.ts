import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { usePersistedState } from './usePersistedState';

describe('usePersistedState', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts with the initial value when nothing is stored', () => {
    const { result } = renderHook(() => usePersistedState('test-key', 'initial'));
    expect(result.current[0]).toBe('initial');
  });

  it('reads a previously stored value on mount', () => {
    localStorage.setItem('test-key', JSON.stringify('from-storage'));
    const { result } = renderHook(() => usePersistedState('test-key', 'initial'));
    expect(result.current[0]).toBe('from-storage');
  });

  it('persists updates to localStorage', () => {
    const { result } = renderHook(() => usePersistedState('test-key', 0));

    act(() => {
      result.current[1](42);
    });

    expect(result.current[0]).toBe(42);
    expect(JSON.parse(localStorage.getItem('test-key')!)).toBe(42);
  });

  it('supports functional updates', () => {
    const { result } = renderHook(() => usePersistedState('test-key', 1));

    act(() => {
      result.current[1]((prev) => prev + 1);
    });

    expect(result.current[0]).toBe(2);
  });
});
