import { describe, expect, it } from 'vitest';
import { sampleGroupCriteria } from './criteriaSample';

describe('sampleGroupCriteria (taqdimot uchun namuna)', () => {
  it('uses fictitious names, never real students, and is stable for a group and day', () => {
    const a = sampleGroupCriteria('DI-2426', '2026-10-06', 18);
    const b = sampleGroupCriteria('DI-2426', '2026-10-06', 18);
    expect(a).toEqual(b);
    expect(a.people).toHaveLength(18);
    expect(a.people.every((p) => p.full_name.startsWith('Namuna talaba ') && p.id.startsWith('namuna-'))).toBe(true);
  });

  it('fills every student criterion with a believable picture', () => {
    const data = sampleGroupCriteria('MD-134/25', '2026-10-06', 25);
    expect(data.criteria.map((c) => c.code)).toEqual([7, 7, 7, 8, 9, 10, 15, 19]);
    expect(data.criteria.every((c) => c.unavailable === null)).toBe(true);
    // Chekish — 1-2 kishida.
    const smokers = data.people.filter((p) => p.cells.chekish.value === '1');
    expect(smokers.length).toBeGreaterThanOrEqual(1);
    expect(smokers.length).toBeLessThanOrEqual(2);
    // Oq xalat — ko'pchilikda bor.
    const coats = data.people.filter((p) => p.cells.forma.value === 'bor').length;
    expect(coats).toBeGreaterThan(data.people.length / 2);
    expect(data.teacher.activity).toBeGreaterThanOrEqual(60);
  });
});
