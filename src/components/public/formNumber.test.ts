import { describe, expect, it } from 'vitest';
import { formNumber, formSerial } from './formNumber';

describe('formSerial', () => {
  it("bo'sh tanlov — 0001", () => {
    expect(formSerial([])).toBe('0001');
    expect(formSerial([undefined, null, '', '   '])).toBe('0001');
  });

  it('bir xil bo\'laklar — doim bir xil raqam (vaqtga bog\'liq emas)', () => {
    const a = formSerial(['pinfl', 'K7M2XR']);
    const b = formSerial(['pinfl', 'K7M2XR']);
    expect(a).toBe(b);
    expect(a).toMatch(/^\d{4}$/);
  });

  it("turli tanlov — turli raqam, lekin doim 0002 dan yuqori", () => {
    const a = formSerial(['pinfl', 'K7M2XR']);
    const b = formSerial(['passport', 'K7M2XR']);
    expect(a).not.toBe(b);
    expect(Number(a)).toBeGreaterThanOrEqual(2);
    expect(Number(b)).toBeGreaterThanOrEqual(2);
  });
});

describe('formNumber', () => {
  it('bosqichsiz forma: TASHKILOT/FORMA/TARTIB', () => {
    expect(formNumber({ kind: 'kirish' })).toBe('FERMI/KIR/0001');
    expect(formNumber({ kind: 'parol' })).toBe('FERMI/PRL/0001');
  });

  it("bosqich berilsa «B2-4» bo'lagi qo'shiladi", () => {
    expect(formNumber({ kind: 'royxat', step: 2, of: 4 })).toBe('FERMI/RYX/B2-4/0001');
  });

  it("bosqich chegaradan tashqarida bo'lsa tushirib qoldiriladi", () => {
    expect(formNumber({ kind: 'royxat', step: 5, of: 4 })).toBe('FERMI/RYX/0001');
    expect(formNumber({ kind: 'royxat', step: 0, of: 4 })).toBe('FERMI/RYX/0001');
  });

  it('tashkilot kodi almashtiriladi va bosh harfga keltiriladi', () => {
    expect(formNumber({ kind: 'kirish', org: 'tdtu' })).toBe('TDTU/KIR/0001');
  });

  it("holat o'zgarsa raqam ham o'zgaradi, lekin qayta hisoblansa o'sha bo'ladi", () => {
    const first = formNumber({ kind: 'royxat', step: 1, of: 4, parts: ['pinfl', 'K7M2XR'] });
    const again = formNumber({ kind: 'royxat', step: 1, of: 4, parts: ['pinfl', 'K7M2XR'] });
    const other = formNumber({ kind: 'royxat', step: 1, of: 4, parts: ['pinfl', 'QQ22DD'] });
    expect(first).toBe(again);
    expect(first).not.toBe(other);
    expect(first).toMatch(/^FERMI\/RYX\/B1-4\/\d{4}$/);
  });
});
