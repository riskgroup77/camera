import { describe, expect, it } from 'vitest';
import { appendPoint, isSelfIntersecting, polygonArea, roundPoint, validatePolygon } from './zonePolygon';

describe('roundPoint / appendPoint', () => {
  it('koordinatani 4 kasr xonagacha yumaloqlaydi', () => {
    expect(roundPoint([0.43277310924369745, 0.111119])).toEqual([0.4328, 0.1111]);
  });

  it('bir joyga ikki marta bosilsa nuqta qo‘shilmaydi', () => {
    const points = appendPoint([], [0.5, 0.5]);
    expect(appendPoint(points, [0.50001, 0.49999])).toBe(points);
  });

  it('boshqa nuqta qo‘shiladi', () => {
    expect(appendPoint([[0.1, 0.1]], [0.2, 0.3])).toEqual([
      [0.1, 0.1],
      [0.2, 0.3],
    ]);
  });
});

describe('polygonArea', () => {
  it('kvadratning yuzi', () => {
    expect(
      polygonArea([
        [0, 0],
        [0, 0.5],
        [0.5, 0.5],
        [0.5, 0],
      ]),
    ).toBeCloseTo(0.25);
  });

  it('bitta chiziqdagi nuqtalarda nol', () => {
    expect(
      polygonArea([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ]),
    ).toBe(0);
  });
});

describe('isSelfIntersecting', () => {
  it('oddiy kvadrat — kesishmaydi', () => {
    expect(
      isSelfIntersecting([
        [0, 0],
        [0, 1],
        [1, 1],
        [1, 0],
      ]),
    ).toBe(false);
  });

  it('«kapalak» shakl — kesishadi', () => {
    expect(
      isSelfIntersecting([
        [0, 0],
        [1, 1],
        [1, 0],
        [0, 1],
      ]),
    ).toBe(true);
  });
});

describe('validatePolygon', () => {
  it('bo‘sh ro‘yxat — zona olib tashlanmoqda, xato emas', () => {
    expect(validatePolygon([])).toBeNull();
  });

  it('2 ta nuqta rad etiladi (backend ham 422 qaytaradi)', () => {
    expect(
      validatePolygon([
        [0, 0],
        [1, 1],
      ]),
    ).toMatch(/kamida 3 ta nuqta/);
  });

  it('bitta chiziqdagi uchta nuqta rad etiladi', () => {
    expect(
      validatePolygon([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ]),
    ).toMatch(/bitta chiziqda/);
  });

  it('o‘z-o‘zini kesuvchi ko‘pburchak rad etiladi', () => {
    expect(
      validatePolygon([
        [0, 0],
        [1, 1],
        [1, 0],
        [0, 1],
      ]),
    ).toMatch(/kesib o‘tmoqda|kesib o'tmoqda/);
  });

  it('to‘g‘ri ko‘pburchak o‘tadi', () => {
    expect(
      validatePolygon([
        [0.1, 0.1],
        [0.1, 0.6],
        [0.7, 0.6],
      ]),
    ).toBeNull();
  });
});
