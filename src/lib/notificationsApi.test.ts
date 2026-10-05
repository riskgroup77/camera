import { describe, expect, it } from 'vitest';
import {
  describeRuleFilters,
  formatLogTime,
  formatUzPhone,
  kindLabel,
  logQuery,
  normalizeUzPhone,
  splitRecipientInput,
  validateRecipient,
} from './notificationsApi';

describe('normalizeUzPhone', () => {
  it.each([
    ['+998 90 123-45-67', '+998901234567'],
    ['998901234567', '+998901234567'],
    ['90 123 45 67', '+998901234567'],
    ['8 90 123 45 67', '+998901234567'],
    ['(97) 000-11-22', '+998970001122'],
  ])('%s -> %s', (raw, expected) => {
    expect(normalizeUzPhone(raw)).toBe(expected);
  });

  it.each(['+7 999 123 45 67', '12345', '', null, undefined])('rejects %s', (raw) => {
    expect(normalizeUzPhone(raw)).toBeNull();
  });
});

describe('formatUzPhone', () => {
  it('groups digits for display', () => {
    expect(formatUzPhone('+998901234567')).toBe('+998 90 123 45 67');
  });
  it('leaves unknown values as they are', () => {
    expect(formatUzPhone('abc')).toBe('abc');
    expect(formatUzPhone(null)).toBe('');
  });
});

describe('validateRecipient', () => {
  it('normalizes phones for sms', () => {
    expect(validateRecipient('sms', ' 90 111 22 33 ')).toEqual(['+998901112233', null]);
    expect(validateRecipient('sms', '123')[1]).toContain("noto'g'ri");
  });
  it('accepts telegram chat ids and channel names', () => {
    expect(validateRecipient('telegram', '123456')).toEqual(['123456', null]);
    expect(validateRecipient('telegram', '-1001234567890')).toEqual(['-1001234567890', null]);
    expect(validateRecipient('telegram', '@navbatchi_kanal')).toEqual(['@navbatchi_kanal', null]);
    expect(validateRecipient('telegram', 'abc def')[1]).toContain('chat ID');
    expect(validateRecipient('telegram', '@ab')[1]).toContain('chat ID');
  });
  it('ignores empty input', () => {
    expect(validateRecipient('telegram', '   ')).toEqual([null, null]);
  });
});

describe('splitRecipientInput', () => {
  it('splits on commas, semicolons and new lines but keeps spaces inside phones', () => {
    expect(splitRecipientInput('+998 90 111 22 33, 123;\n-100 ')).toEqual(['+998 90 111 22 33', '123', '-100']);
  });
});

describe('labels and queries', () => {
  it('labels known and parent kinds', () => {
    expect(kindLabel('camera_offline')).toBe("Kamera o'chdi");
    expect(kindLabel('parent_absence')).toBe('Ota-ona: kelmadi');
    expect(kindLabel('boshqa')).toBe('boshqa');
  });

  it('describes rule filters', () => {
    const parts = describeRuleFilters(
      { moduleCodes: [3], buildingIds: ['b1'], minSeverity: 'yuqori' },
      (code) => `#${code}`,
      (id) => (id === 'b1' ? 'Bosh bino' : id),
    );
    expect(parts).toEqual(['Modullar: #3', 'Binolar: Bosh bino', 'Daraja: Faqat yuqori']);
    expect(describeRuleFilters({ moduleCodes: null, buildingIds: [], minSeverity: null }, String, String)).toEqual([]);
  });

  it('builds log query without empty filters', () => {
    expect(logQuery({ page: 2, pageSize: 20, status: '', channel: 'sms', search: '  90 ' })).toBe(
      'page=2&pageSize=20&channel=sms&search=90',
    );
  });
});

describe('formatLogTime', () => {
  it('keeps server (Tashkent) clock time', () => {
    expect(formatLogTime('2026-09-19T14:05:07+05:00')).toBe('19.09.2026 14:05:07');
    expect(formatLogTime('')).toBe('');
  });
});
