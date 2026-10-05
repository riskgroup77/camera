import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { connectionState, WallHeader } from './WallHeader';

/** Devor ekrani kunlab qarovsiz turadi. So'rov xatoga uchramasdan
 *  "osilib" qolsa (tarmoq qora tuynuk, proksi ushlab qolgan ulanish),
 *  `online` true bo'lib qolaveradi va ekranda ertalabki raqamlar
 *  kechqurun ham yashil "Ulangan" yozuvi bilan turardi. */
describe('WallHeader — eskirgan maʼlumot', () => {
  const at = (iso: string) => new Date(iso);

  it('yangi javob — "Ulangan"', () => {
    const s = connectionState(true, at('2026-09-20T10:00:00Z'), at('2026-09-20T10:00:30Z'));
    expect(s.ok).toBe(true);
    expect(s.label).toBe('Ulangan');
  });

  it("uzilganda oxirgi yangilanish vaqti ko'rsatiladi", () => {
    const s = connectionState(false, at('2026-09-20T10:00:00Z'), at('2026-09-20T10:00:30Z'));
    expect(s.ok).toBe(false);
    expect(s.label).toBe('Uzildi');
    expect(s.title).toContain('Ulanish uzildi');
  });

  it("so'rov osilib qolganda ham (online, lekin eski) ogohlantiradi", () => {
    const s = connectionState(true, at('2026-09-20T03:00:00Z'), at('2026-09-20T13:00:00Z'));
    expect(s.ok).toBe(false);
    expect(s.label).toBe('Eskirgan');
    expect(s.title).toContain('10 soat');
  });

  it('bir necha daqiqa kechikish — daqiqada yoziladi', () => {
    const s = connectionState(true, at('2026-09-20T10:00:00Z'), at('2026-09-20T10:05:00Z'));
    expect(s.ok).toBe(false);
    expect(s.label).toBe('Eskirgan');
    expect(s.title).toContain('5 daqiqa');
  });

  it('ekranda eskirgan holat matni chiqadi', () => {
    render(<WallHeader online updatedAt={new Date(Date.now() - 45 * 60_000)} />);
    expect(screen.getByText('Eskirgan')).toBeInTheDocument();
  });
});
