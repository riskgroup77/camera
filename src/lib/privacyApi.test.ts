import { describe, expect, it } from 'vitest';
import {
  confirmationWord,
  consentState,
  daysUntil,
  exportFilename,
  formatRetentionDays,
  formatRetentionHours,
  formatUzDate,
  matchesConfirmation,
} from './privacyApi';

describe('consentState', () => {
  it('rozilik joriy versiyaga berilgan', () => {
    expect(consentState({ hasBiometrics: true, consentGivenAt: '2026-09-01T00:00:00Z', consentCurrent: true })).toBe(
      'current',
    );
  });

  it('eski versiyaga berilgan rozilik eskirgan', () => {
    expect(consentState({ hasBiometrics: true, consentGivenAt: '2026-01-01T00:00:00Z', consentCurrent: false })).toBe(
      'outdated',
    );
  });

  it("biometrikasi bor, rozilik yo'q", () => {
    expect(consentState({ hasBiometrics: true, consentGivenAt: null, consentCurrent: false })).toBe('missing');
  });

  it("biometrikasi yo'q odamga rozilik kerak emas", () => {
    expect(consentState({ hasBiometrics: false, consentGivenAt: null, consentCurrent: false })).toBe('not_needed');
  });
});

describe('formatRetentionHours', () => {
  it('soat, butun kun va 0', () => {
    expect(formatRetentionHours(4)).toBe('4 soat');
    expect(formatRetentionHours(48)).toBe('2 kun');
    expect(formatRetentionHours(0)).toBe('Saqlanmaydi');
  });
});

describe('formatRetentionDays', () => {
  it('kun va yil', () => {
    expect(formatRetentionDays(30)).toBe('30 kun');
    expect(formatRetentionDays(365)).toBe('1 yil');
    expect(formatRetentionDays(730)).toBe('2 yil');
  });

  it("0 — muddat yo'q", () => {
    expect(formatRetentionDays(0)).toBe('Cheklanmagan');
    expect(formatRetentionDays(0, 'Hodisa bilan')).toBe('Hodisa bilan');
  });
});

describe('formatUzDate / daysUntil', () => {
  it('Toshkent sanasi', () => {
    // 19:30 UTC — Toshkentda ertasi kun.
    expect(formatUzDate('2026-09-19T19:30:00Z')).toBe('20.09.2026');
    expect(formatUzDate(null)).toBe('—');
    expect(formatUzDate('buzuq')).toBe('—');
  });

  it('qolgan kunlar', () => {
    const now = new Date('2026-09-19T00:00:00Z');
    expect(daysUntil('2026-09-29T00:00:00Z', now)).toBe(10);
    expect(daysUntil('2026-09-18T00:00:00Z', now)).toBe(-1);
    expect(daysUntil(null, now)).toBeNull();
  });
});

describe('typed confirmation', () => {
  it('familiya tasdiqlash so‘zi', () => {
    expect(confirmationWord('  Karimov Aziz Olimovich ')).toBe('Karimov');
    expect(confirmationWord('')).toBe("O'CHIRISH");
  });

  it('katta-kichik harf va bo‘sh joy farq qilmaydi', () => {
    expect(matchesConfirmation(' karimov ', 'Karimov')).toBe(true);
    expect(matchesConfirmation('Karim', 'Karimov')).toBe(false);
    expect(matchesConfirmation('', '')).toBe(false);
  });
});

describe('exportFilename', () => {
  it('lotincha slug va sana', () => {
    const now = new Date('2026-09-19T10:00:00Z');
    expect(exportFilename({ fullName: "G'ulomov O'tkir", id: 'x' }, now)).toBe(
      'shaxsiy-malumot-gulomov-otkir-2026-09-19.json',
    );
    expect(exportFilename({ fullName: 'Иванов', id: 'abc' }, now)).toBe('shaxsiy-malumot-abc-2026-09-19.json');
  });
});
