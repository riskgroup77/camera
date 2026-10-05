import { describe, expect, it } from 'vitest';
import { shortEventTime } from './EventsPage';

describe('shortEventTime', () => {
  it('bugun faqat soat, boshqa kun sana bilan', () => {
    expect(shortEventTime('2026-09-24 12:05', '2026-09-24')).toBe('12:05');
    expect(shortEventTime('2026-09-23 08:41', '2026-09-24')).toBe('23.09 08:41');
    expect(shortEventTime('noma’lum', '2026-09-24')).toBe('noma’lum');
  });
});
