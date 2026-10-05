import { describe, expect, it } from 'vitest';
import { accuracyPath, indexAfterRemoval, percent, precisionRag, reviewKeyAction } from './tekshiruvApi';

const key = (k: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  ...mods,
});

describe('reviewKeyAction', () => {
  it('T — ha, R — yo‘q (katta harf va kirill tartibida ham)', () => {
    expect(reviewKeyAction(key('t'))).toBe('confirm');
    expect(reviewKeyAction(key('T'))).toBe('confirm');
    expect(reviewKeyAction(key('е'))).toBe('confirm');
    expect(reviewKeyAction(key('r'))).toBe('reject');
    expect(reviewKeyAction(key('к'))).toBe('reject');
  });

  it('strelkalar navbatda yuradi', () => {
    expect(reviewKeyAction(key('ArrowRight'))).toBe('next');
    expect(reviewKeyAction(key('ArrowLeft'))).toBe('prev');
  });

  it('Ctrl+R kabi brauzer tugmalarini ushlamaydi', () => {
    expect(reviewKeyAction(key('r', { ctrlKey: true }))).toBeNull();
    expect(reviewKeyAction(key('t', { metaKey: true }))).toBeNull();
    expect(reviewKeyAction(key('x'))).toBeNull();
  });
});

describe('indexAfterRemoval', () => {
  it('o‘sha o‘rinda qoladi, oxirgisi o‘chsa — orqaga', () => {
    expect(indexAfterRemoval(1, 3)).toBe(1);
    expect(indexAfterRemoval(3, 3)).toBe(2);
    expect(indexAfterRemoval(0, 0)).toBe(0);
  });
});

describe('precisionRag', () => {
  it('kam qarorli modulga rang bermaydi', () => {
    expect(precisionRag({ confirmed: 2, rejected: 0, precision: 1 })).toBe('yoq');
  });

  it('90% dan yashil, 75% dan sariq, pastda qizil', () => {
    expect(precisionRag({ confirmed: 19, rejected: 1, precision: 0.95 })).toBe('yashil');
    expect(precisionRag({ confirmed: 8, rejected: 2, precision: 0.8 })).toBe('sariq');
    expect(precisionRag({ confirmed: 5, rejected: 5, precision: 0.5 })).toBe('qizil');
  });
});

describe('percent', () => {
  it('ulushni foizga aylantiradi', () => {
    expect(percent(0.463)).toBe('46%');
    expect(percent(null)).toBe('—');
  });
});

describe('accuracyPath', () => {
  it('kun parametri bilan', () => {
    expect(accuracyPath(7)).toBe('/api/tekshiruv/aniqlik?kun=7');
  });
});
