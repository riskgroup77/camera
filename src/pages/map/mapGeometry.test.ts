import { describe, expect, it } from 'vitest';
import { angleBetween, clamp01, conePath, coneRadius, fitSize, normalizeAngle, polar, toNormalized, toPixels } from './mapGeometry';

describe('mapGeometry', () => {
  it('clamps and normalizes', () => {
    expect(clamp01(-0.2)).toBe(0);
    expect(clamp01(1.4)).toBe(1);
    expect(clamp01(0.3)).toBe(0.3);
    expect(normalizeAngle(-90)).toBe(270);
    expect(normalizeAngle(720)).toBe(0);
    expect(normalizeAngle(359.6)).toBe(0);
  });

  it('fits the plan into the container keeping aspect ratio', () => {
    expect(fitSize({ width: 800, height: 600 }, { width: 2000, height: 1000 })).toEqual({ width: 800, height: 400 });
    expect(fitSize({ width: 800, height: 300 }, { width: 2000, height: 1000 })).toEqual({ width: 600, height: 300 });
    expect(fitSize({ width: 0, height: 300 }, { width: 10, height: 10 })).toEqual({ width: 0, height: 0 });
  });

  it('converts screen points to normalized coordinates and back', () => {
    const rect = { left: 100, top: 50, width: 400, height: 200 };
    expect(toNormalized(300, 100, rect)).toEqual({ x: 0.5, y: 0.25 });
    // Chetdan tashqari — chetga yopishadi.
    expect(toNormalized(0, 999, rect)).toEqual({ x: 0, y: 1 });
    expect(toPixels({ x: 0.5, y: 0.25 }, { width: 400, height: 200 })).toEqual({ x: 200, y: 50 });
  });

  it('uses compass angles: 0 is up, 90 is right', () => {
    const c = { x: 10, y: 10 };
    const up = polar(c, 0, 5);
    expect(up.x).toBeCloseTo(10);
    expect(up.y).toBeCloseTo(5);
    const right = polar(c, 90, 5);
    expect(right.x).toBeCloseTo(15);
    expect(right.y).toBeCloseTo(10);
    expect(angleBetween(c, { x: 10, y: 0 })).toBe(0);
    expect(angleBetween(c, { x: 20, y: 10 })).toBe(90);
    expect(angleBetween(c, { x: 10, y: 20 })).toBe(180);
    expect(angleBetween(c, { x: 0, y: 10 })).toBe(270);
    expect(angleBetween(c, c)).toBe(0);
  });

  it('builds a sector path for the field of view', () => {
    // 90° konus yuqoriga: -45°..+45°.
    const path = conePath({ x: 0, y: 0 }, 0, 90, 10);
    expect(path).toBe('M 0 0 L -7.07 -7.07 A 10 10 0 0 1 7.07 -7.07 Z');
    // 180° dan keng — katta yoy bayrog'i.
    expect(conePath({ x: 0, y: 0 }, 0, 270, 10)).toContain(' 0 1 1 ');
    // 360° — to'liq doira, markazdan chiziq yo'q.
    const full = conePath({ x: 5, y: 5 }, 0, 360, 5);
    expect(full.startsWith('M 5 0 A')).toBe(true);
    expect(conePath({ x: 0, y: 0 }, 0, 90, 0)).toBe('');
  });

  it('keeps cones visible on small plans', () => {
    expect(coneRadius({ width: 100, height: 80 })).toBe(28);
    expect(coneRadius({ width: 1000, height: 800 })).toBe(72);
  });
});
