import { describe, expect, it } from 'vitest';
import {
  courseOptions,
  drillPatch,
  formatCell,
  groupOptions,
  hisobotPaths,
  buildReference,
  documentReference,
  printScopeNote,
  readState,
  writeState,
  type HisobotFilterOptions,
} from './hisobotApi';

const TODAY = '2026-09-19';

const OPTIONS: HisobotFilterOptions = {
  faculties: [],
  courses: [1, 2],
  units: [],
  unit_kinds: [],
  groups: [
    { faculty_id: 'di', course: 2, name: 'DI-2302', count: 3 },
    { faculty_id: 'di', course: 2, name: 'DI-2301', count: 5 },
    { faculty_id: 'di', course: 3, name: 'DI-2101', count: 4 },
    { faculty_id: 'pe', course: 1, name: 'PE-2501', count: 2 },
  ],
};

describe('readState', () => {
  it('defaults to staff, today', () => {
    const s = readState(new URLSearchParams(), TODAY);
    expect(s).toMatchObject({ section: 'xodimlar', preset: 'today', from: TODAY, to: TODAY, criterion: '' });
  });

  it('ignores the other section filters', () => {
    const s = readState(new URLSearchParams('bolim=xodimlar&fakultet=di&bolinma=u-1'), TODAY);
    expect(s.faculty).toBe('');
    expect(s.unit).toBe('u-1');
    const t = readState(new URLSearchParams('bolim=talabalar&fakultet=di&bolinma=u-1'), TODAY);
    expect(t.faculty).toBe('di');
    expect(t.unit).toBe('');
  });

  it('accepts a valid custom range and rejects a reversed one', () => {
    expect(readState(new URLSearchParams('davr=custom&dan=2026-09-01&gacha=2026-09-10'), TODAY)).toMatchObject({
      preset: 'custom',
      from: '2026-09-01',
      to: '2026-09-10',
    });
    expect(readState(new URLSearchParams('davr=custom&dan=2026-09-10&gacha=2026-09-01'), TODAY)).toMatchObject({
      preset: 'today',
      from: TODAY,
    });
  });
});

describe('writeState', () => {
  it('clears dependent filters on cascade', () => {
    const cur = new URLSearchParams('bolim=talabalar&fakultet=di&kurs=2&guruh=DI-2301');
    expect(writeState(cur, { course: '3' }).toString()).toBe('bolim=talabalar&fakultet=di&kurs=3');
    expect(writeState(cur, { faculty: 'pe' }).toString()).toBe('bolim=talabalar&fakultet=pe');
  });

  it('drops section-specific params when the section changes', () => {
    const cur = new URLSearchParams('bolim=talabalar&fakultet=di&mezon=uxlash&q=ali&davr=week');
    expect(writeState(cur, { section: 'xodimlar' }).toString()).toBe('davr=week');
    expect(writeState(cur, { section: 'talabalar' }).get('mezon')).toBe('uxlash');
  });

  it('stores custom dates only for the custom preset', () => {
    const cur = new URLSearchParams('davr=custom&dan=2026-09-01&gacha=2026-09-10');
    expect(writeState(cur, { preset: 'month', from: '2026-09-01', to: TODAY }).toString()).toBe('davr=month');
  });
});

describe('cascading options', () => {
  it('limits courses and groups to the chosen faculty/course', () => {
    expect(courseOptions(OPTIONS, 'di')).toEqual([2, 3]);
    expect(courseOptions(OPTIONS, '')).toEqual([1, 2, 3]);
    expect(groupOptions(OPTIONS, 'di', '2')).toEqual(['DI-2301', 'DI-2302']);
    expect(groupOptions(OPTIONS, 'pe', '')).toEqual(['PE-2501']);
  });
});

describe('drillPatch', () => {
  const base = readState(new URLSearchParams('bolim=talabalar'), TODAY);
  it('goes one level deeper', () => {
    expect(drillPatch(base, 'di')).toEqual({ faculty: 'di' });
    expect(drillPatch({ ...base, faculty: 'di' }, '2')).toEqual({ course: '2' });
    expect(drillPatch({ ...base, faculty: 'di' }, '0')).toBeNull();
    expect(drillPatch({ ...base, faculty: 'di', course: '2' }, 'DI-2301')).toEqual({ group: 'DI-2301' });
    expect(drillPatch({ ...base, faculty: 'di', course: '2', group: 'DI-2301' }, 'x')).toBeNull();
    const staff = readState(new URLSearchParams(), TODAY);
    expect(drillPatch(staff, 'u-1')).toEqual({ unit: 'u-1' });
  });
});

describe('misc', () => {
  it('builds the report path with only set filters', () => {
    const s = readState(new URLSearchParams('bolim=talabalar&fakultet=di&mezon=davomat'), TODAY);
    const path = hisobotPaths.report(s);
    expect(path).toContain('kind=talaba');
    expect(path).toContain('faculty=di');
    expect(path).not.toContain('unit=');
  });

  it('formats cells', () => {
    expect(formatCell(87.5, '%')).toBe('87,5%');
    expect(formatCell(3, '')).toBe('3');
    expect(formatCell(null, '%')).toBe('—');
    // Bitta kun tanlanganda jadvalda matnli kataklar ham bor (vaqt, holat, izoh).
    expect(formatCell('08:15', '')).toBe('08:15');
    expect(formatCell('Kech keldi', '')).toBe('Kech keldi');
    expect(formatCell('', '')).toBe('—');
  });

  it("chop etilgan hujjat jadval chegarasini so'z bilan aytadi", () => {
    // Ming ajratgichi brauzer/Node lokaliga bog'liq — xuddi shu tarzda tuzamiz.
    const ru = (value: number) => value.toLocaleString('ru-RU');

    // Ko'rsatkichlar 4120 kishini qamragan, jadvalda esa 1890 tadan 300 qator.
    const cut = printScopeNote(4120, 300, 1890);
    expect(cut).toContain(`${ru(4120)} kishi`);
    expect(cut).toContain(ru(1890));
    expect(cut).toContain('300');
    expect(cut).toContain('Excel');

    // Jadval to'liq bo'lsa — chegara haqida gapirilmaydi.
    const full = printScopeNote(4120, 42, 42);
    expect(full).toContain(`${ru(4120)} kishi`);
    expect(full).toContain('hammasi');
    expect(full).not.toContain('Excel');
  });
});

/* ------------------------------------------------------------------
 * Hujjat raqami — qog'ozdagi varaqni ekrandagi ko'rinish bilan
 * bog'laydigan yagona kod. Eng muhim xossasi: DETERMINISTIK.
 * ---------------------------------------------------------------- */
describe('Hujjat raqami', () => {
  it("shakli: TASHKILOT/TUR/DAVR/BO'LIM-TARTIB", () => {
    const state = readState(new URLSearchParams('bolim=xodimlar&korinish=tabel&oy=2026-09'), TODAY);
    expect(documentReference(state)).toBe('FERMI/TBL/2026-09/XDM-0001');
  });

  it('talabalar bo\'limi boshqa kod beradi', () => {
    const state = readState(new URLSearchParams('bolim=talabalar&korinish=tabel&oy=2026-09'), TODAY);
    expect(documentReference(state)).toBe('FERMI/TBL/2026-09/TLB-0001');
  });

  it("bir xil holat — doim bir xil kod (hujjat raqami o'zgarib ketmaydi)", () => {
    const search = 'bolim=talabalar&korinish=tabel&oy=2026-09&fakultet=f1&guruh=101-guruh';
    const a = documentReference(readState(new URLSearchParams(search), TODAY));
    const b = documentReference(readState(new URLSearchParams(search), '2027-01-05'));
    expect(a).toBe(b);
    // Filtr qo'yilgan — bu endi "butun bo'lim" hujjati emas.
    expect(a).not.toContain('-0001');
    expect(a).toMatch(/^FERMI\/TBL\/2026-09\/TLB-\d{4}$/);
  });

  it('boshqa tanlov — boshqa tartib raqami', () => {
    const one = documentReference(readState(new URLSearchParams('bolim=talabalar&korinish=tabel&oy=2026-09&guruh=101-guruh'), TODAY));
    const two = documentReference(readState(new URLSearchParams('bolim=talabalar&korinish=tabel&oy=2026-09&guruh=102-guruh'), TODAY));
    expect(one).not.toBe(two);
  });

  it('holat taxtasida davr — oraliq, turi HLT', () => {
    const state = readState(new URLSearchParams('bolim=xodimlar&davr=today'), TODAY);
    expect(documentReference(state)).toMatch(/^FERMI\/HLT\/20260919-20260919\/XDM-\d{4}$/);
  });

  it("ro'yxat ko'rinishi alohida turga ega (RYX)", () => {
    const state = readState(new URLSearchParams('bolim=xodimlar&korinish=royxat&davr=today'), TODAY);
    expect(documentReference(state)).toMatch(/^FERMI\/RYX\//);
  });

  it('eski `tahlil` havolasi holat taxtasiga tushadi', () => {
    expect(readState(new URLSearchParams('korinish=tahlil'), TODAY).view).toBe('taxta');
  });

  it('tashkilot kodi almashtiriladi va bosh harfga keltiriladi', () => {
    const state = readState(new URLSearchParams('bolim=xodimlar&korinish=tabel&oy=2026-09'), TODAY);
    expect(documentReference(state, 'qmii')).toBe('QMII/TBL/2026-09/XDM-0001');
  });

  it('buildReference bo\'laklardan ham kod tuzadi (jadval o\'z holatini bilmaydi)', () => {
    expect(buildReference({ view: 'tabel', section: 'talabalar', period: '2026-09' })).toBe(
      'FERMI/TBL/2026-09/TLB-0001',
    );
    const withScope = buildReference({
      view: 'tabel',
      section: 'talabalar',
      period: '2026-09',
      parts: ['Davolash ishi, 2-kurs'],
    });
    expect(withScope).toMatch(/^FERMI\/TBL\/2026-09\/TLB-\d{4}$/);
    expect(withScope).not.toContain('-0001');
  });
});
