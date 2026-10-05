import { describe, expect, it } from 'vitest';
import { cleanTotpCode, groupSecret } from './twoFactorApi';

describe('twoFactorApi yordamchilari', () => {
  it('kodni tozalaydi: bo‘shliq va chiziqcha qabul qilinadi', () => {
    expect(cleanTotpCode('123456')).toBe('123456');
    expect(cleanTotpCode(' 123 456 ')).toBe('123456');
    expect(cleanTotpCode('123-456')).toBe('123456');
    expect(cleanTotpCode('12345')).toBeNull();
    expect(cleanTotpCode('12a456')).toBeNull();
    expect(cleanTotpCode('1234567')).toBeNull();
  });

  it('kalitni 4 belgidan guruhlaydi', () => {
    expect(groupSecret('ABCDEFGHIJ')).toBe('ABCD EFGH IJ');
  });
});
