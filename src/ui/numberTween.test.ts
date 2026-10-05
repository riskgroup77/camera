import { describe, expect, it } from 'vitest';
import { easeOut, formatLike, parseDisplayNumber } from './numberTween';

describe('parseDisplayNumber', () => {
  it('parses grouped integers and decimals with suffixes', () => {
    expect(parseDisplayNumber('1 234')).toMatchObject({ value: 1234, decimals: 0, grouped: true });
    expect(parseDisplayNumber('87,5%')).toMatchObject({ value: 87.5, decimals: 1, suffix: '%' });
    expect(parseDisplayNumber('12')).toMatchObject({ value: 12, decimals: 0, grouped: false });
  });
  it('rejects non-numbers and clock times', () => {
    expect(parseDisplayNumber('—')).toBeNull();
    expect(parseDisplayNumber('08:12')).toBeNull();
  });
  it('round-trips through formatLike', () => {
    const p = parseDisplayNumber('5\u00a0938')!;
    expect(formatLike(p.value, p)).toBe('5\u00a0938');
    const q = parseDisplayNumber('87,5%')!;
    expect(formatLike(43.25, q)).toBe('43,3%');
  });
  it('eases to 1', () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(2)).toBe(1);
  });
});
