import { describe, expect, it } from 'vitest';
import { ipAddress, minLength, numberRange, required } from './validation';

describe('required', () => {
  it('returns an error message for empty/whitespace input', () => {
    expect(required('')).toBeDefined();
    expect(required('   ')).toBeDefined();
  });

  it('returns undefined for non-empty input', () => {
    expect(required('Jamshid')).toBeUndefined();
  });
});

describe('minLength', () => {
  it('rejects strings shorter than the minimum', () => {
    expect(minLength('ab', 3)).toBeDefined();
  });

  it('accepts strings at or above the minimum', () => {
    expect(minLength('abc', 3)).toBeUndefined();
  });
});

describe('ipAddress', () => {
  it('accepts a well-formed IPv4 address', () => {
    expect(ipAddress('192.168.1.10')).toBeUndefined();
  });

  it.each(['192.168.1', '192.168.1.256', 'not-an-ip', '1.2.3.4.5'])(
    'rejects malformed input: %s',
    (value) => {
      expect(ipAddress(value)).toBeDefined();
    },
  );
});

describe('numberRange', () => {
  it('rejects non-numeric input', () => {
    expect(numberRange('abc', 0, 100)).toBeDefined();
  });

  it('rejects values outside the range', () => {
    expect(numberRange('150', 0, 100)).toBeDefined();
  });

  it('accepts values inside the range', () => {
    expect(numberRange('50', 0, 100)).toBeUndefined();
  });
});
