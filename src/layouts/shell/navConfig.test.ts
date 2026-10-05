import { describe, expect, it } from 'vitest';
import { findActive, homeForRole, isPathAllowedForRole, matchesPath, usesViewDate, visibleSections } from './navConfig';
import { legacyRedirect, videoWallEntry } from '../legacyRoutes';

describe('navConfig', () => {
  it('matches nested paths but not prefixes of other words', () => {
    expect(matchesPath('/talabalar/guruh/D-101', '/talabalar')).toBe(true);
    expect(matchesPath('/talabalarim', '/talabalar')).toBe(false);
    expect(matchesPath('/hodisalar', '/')).toBe(false);
    expect(matchesPath('/', '/')).toBe(true);
  });

  it('finds the active item and its section', () => {
    expect(findActive('/talabalar/fakultet/3')?.item.label).toBe('Talabalar');
    expect(findActive('/sozlamalar/kameralar')?.section.label).toBe('Sozlamalar');
    expect(findActive('/')?.item.label).toBe('Nazorat');
    expect(findActive('/sozlamalar/ui')).toBeNull();
  });

  it('restricts the camera steward role to its pages', () => {
    expect(homeForRole('kamera-masuli')).toBe('/sozlamalar/kameralar');
    expect(homeForRole('admin')).toBe('/');
    expect(isPathAllowedForRole('kamera-masuli', '/tuzilma')).toBe(true);
    expect(isPathAllowedForRole('kamera-masuli', '/')).toBe(false);
    expect(isPathAllowedForRole('kamera-masuli', '/hodisalar')).toBe(false);
    expect(isPathAllowedForRole('admin', '/hodisalar')).toBe(true);
    expect(isPathAllowedForRole('kamera-masuli', '/tekshiruv')).toBe(false);

    const sections = visibleSections(() => true, 'kamera-masuli');
    expect(sections.flatMap((s) => s.items.map((i) => i.to))).toEqual(['/tuzilma', '/sozlamalar/kameralar']);
  });

  it('filters the menu by permission and drops empty sections', () => {
    const sections = visibleSections((key) => key === 'viewLive', 'admin');
    expect(sections.map((s) => s.id)).toEqual(['monitoring', 'malumotlar']);
    expect(sections[0].items.map((i) => i.to)).toEqual(['/', '/videodevor', '/xarita', '/shaxs-qidirish']);
  });

  it('shows the date picker only on attendance pages', () => {
    expect(usesViewDate('/')).toBe(true);
    expect(usesViewDate('/shaxs/12')).toBe(false);
    expect(usesViewDate('/hodisalar')).toBe(false);
  });
});

describe('legacyRedirect', () => {
  it('maps old admin URLs and keeps query strings', () => {
    expect(legacyRedirect('/admin')).toBe('/');
    expect(legacyRedirect('/admin/')).toBe('/');
    expect(legacyRedirect('/admin/events', '?id=42')).toBe('/hodisalar?id=42');
    expect(legacyRedirect('/admin/attendance', '?person=abc-1')).toBe('/shaxs/abc-1');
    expect(legacyRedirect('/admin/attendance')).toBe('/talabalar');
    expect(legacyRedirect('/admin/students-staff', '?search=00+12')).toBe('/reestr?search=00+12');
    expect(legacyRedirect('/admin/reset-password', '?token=abc')).toBe('/parolni-tiklash?token=abc');
    expect(legacyRedirect('/admin/system-log')).toBe('/sozlamalar/tizim?tab=jurnal');
    expect(legacyRedirect('/admin/system-log', '?tab=x&q=1')).toBe('/sozlamalar/tizim?tab=jurnal&q=1');
    expect(legacyRedirect('/admin/video-wall', '', '#a')).toBe('/videodevor#a');
    expect(legacyRedirect('/admin/nomalum')).toBe('/');
  });
});

describe('videoWallEntry', () => {
  it("eski «Bino va qavat bo'yicha» parametrlarini tozalaydi", () => {
    const entry = videoWallEntry('?tab=binolar&bino=b-1&qavat=2&kamera=cam-7&q=kirish');
    expect(entry).toEqual({ search: 'kirish', cameraId: 'cam-7', nextSearch: '', changed: true });
  });

  it('boshqa parametrlarga tegmaydi', () => {
    expect(videoWallEntry('?view=v1')).toEqual({ search: '', cameraId: null, nextSearch: 'view=v1', changed: false });
    expect(videoWallEntry('')).toEqual({ search: '', cameraId: null, nextSearch: '', changed: false });
    expect(videoWallEntry('?view=v1&q=zal').nextSearch).toBe('view=v1');
  });
});
