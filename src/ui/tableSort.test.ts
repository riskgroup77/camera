import { describe, expect, it } from 'vitest';
import { compareValues, nextSort, sortRows } from './tableSort';

describe('sortRows', () => {
  const rows = [
    { name: 'Guruh 10', rate: 80 },
    { name: 'Guruh 2', rate: null },
    { name: 'guruh 1', rate: 95 },
    { name: 'Guruh 3', rate: 80 },
  ];

  it('sorts strings naturally and case-insensitively', () => {
    expect(sortRows(rows, (r) => r.name, 'asc').map((r) => r.name)).toEqual(['guruh 1', 'Guruh 2', 'Guruh 3', 'Guruh 10']);
    expect(sortRows(rows, (r) => r.name, 'desc').map((r) => r.name)).toEqual(['Guruh 10', 'Guruh 3', 'Guruh 2', 'guruh 1']);
  });

  it('keeps empty values last in both directions and is stable for ties', () => {
    expect(sortRows(rows, (r) => r.rate, 'asc').map((r) => r.name)).toEqual(['Guruh 10', 'Guruh 3', 'guruh 1', 'Guruh 2']);
    expect(sortRows(rows, (r) => r.rate, 'desc').map((r) => r.name)).toEqual(['guruh 1', 'Guruh 10', 'Guruh 3', 'Guruh 2']);
  });

  it('does not mutate the input', () => {
    const copy = [...rows];
    sortRows(rows, (r) => r.rate, 'asc');
    expect(rows).toEqual(copy);
  });

  it('compares dates, booleans and numbers', () => {
    expect(compareValues(new Date('2026-01-02'), new Date('2026-01-01'))).toBeGreaterThan(0);
    expect(compareValues(false, true)).toBeLessThan(0);
    expect(compareValues(2, 10)).toBeLessThan(0);
  });
});

describe('nextSort', () => {
  it('cycles none → first dir → other dir → none', () => {
    const a = nextSort(null, 'rate');
    expect(a).toEqual({ key: 'rate', dir: 'asc' });
    const b = nextSort(a, 'rate');
    expect(b).toEqual({ key: 'rate', dir: 'desc' });
    expect(nextSort(b, 'rate')).toBeNull();
  });

  it('respects a descending-first column and resets when switching columns', () => {
    expect(nextSort(null, 'rate', 'desc')).toEqual({ key: 'rate', dir: 'desc' });
    expect(nextSort({ key: 'rate', dir: 'desc' }, 'rate', 'desc')).toEqual({ key: 'rate', dir: 'asc' });
    expect(nextSort({ key: 'rate', dir: 'asc' }, 'name')).toEqual({ key: 'name', dir: 'asc' });
  });
});
