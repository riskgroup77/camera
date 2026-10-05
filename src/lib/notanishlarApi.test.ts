import { describe, expect, it } from 'vitest';
import { likelihoodHint, sightingTime } from './notanishlarApi';

describe('sightingTime', () => {
  it("Toshkent vaqtida ko'rsatadi", () => {
    // 06:05 UTC — Toshkentda 11:05.
    expect(sightingTime('2026-09-24T06:05:00Z')).toBe('11:05');
  });
});

describe('likelihoodHint', () => {
  it("o'xshashlik yuqori bo'lsa operatorga ishora beradi", () => {
    expect(likelihoodHint(0.41)).toMatch(/o.xshaydi/);
  });

  it("past o'xshashlikda jim turadi", () => {
    expect(likelihoodHint(0.12)).toBeNull();
    expect(likelihoodHint(null)).toBeNull();
  });
});
