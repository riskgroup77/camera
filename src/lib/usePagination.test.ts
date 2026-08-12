import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { usePagination } from './usePagination';

describe('usePagination', () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1);

  it('slices the first page by default', () => {
    const { result } = renderHook(() => usePagination(items, 10));
    expect(result.current.page).toBe(1);
    expect(result.current.pageItems).toEqual(items.slice(0, 10));
    expect(result.current.totalPages).toBe(3);
  });

  it('moves to the requested page', () => {
    const { result } = renderHook(() => usePagination(items, 10));

    act(() => {
      result.current.setPage(2);
    });

    expect(result.current.pageItems).toEqual(items.slice(10, 20));
  });

  it('clamps back to the last page when the list shrinks', () => {
    let list = items;
    const { result, rerender } = renderHook(() => usePagination(list, 10));

    act(() => {
      result.current.setPage(3);
    });
    expect(result.current.page).toBe(3);

    list = items.slice(0, 5);
    rerender();

    expect(result.current.page).toBe(1);
  });

  it('always reports at least one total page for an empty list', () => {
    const { result } = renderHook(() => usePagination([], 10));
    expect(result.current.totalPages).toBe(1);
    expect(result.current.pageItems).toEqual([]);
  });
});
