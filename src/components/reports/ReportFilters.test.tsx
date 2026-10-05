// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ReportFilters from './ReportFilters';
import { hisobotPaths, readState, type HisobotFilterOptions, type HisobotState } from '../../lib/hisobotApi';

/**
 * FilterBar'ga o'tkazilgandan keyin filtrlar AYNAN o'sha holat kalitlarini
 * yozishini tekshiradi. Excel eksporti URL'i shu holatdan tuziladi
 * (hisobotPaths.export), shuning uchun bitta kalit adashsa yuklab olish
 * jimgina noto'g'ri fayl berardi.
 */

const TODAY = '2026-09-19';

const OPTIONS: HisobotFilterOptions = {
  faculties: [{ id: 'f1', name: 'Davolash ishi', count: 120 }],
  courses: [1, 2, 3],
  units: [{ id: 'u1', name: 'Kafedra A', count: 10, kind: 'kafedra' }],
  unit_kinds: [{ id: 'kafedra', label: 'Kafedra' }],
  groups: [{ name: '101-guruh', faculty_id: 'f1', course: 1, count: 25 }],
};

function studentState(patch: Partial<HisobotState> = {}): HisobotState {
  return { ...readState(new URLSearchParams('bolim=talabalar'), TODAY), ...patch };
}

function staffState(patch: Partial<HisobotState> = {}): HisobotState {
  return { ...readState(new URLSearchParams('bolim=xodimlar'), TODAY), ...patch };
}

function renderFilters(state: HisobotState) {
  const onChange = vi.fn();
  const onReset = vi.fn();
  render(<ReportFilters state={state} options={OPTIONS} onChange={onChange} onReset={onReset} />);
  return { onChange, onReset };
}

describe('ReportFilters — holat kalitlari', () => {
  it('talabalar bo\'limida fakultet/kurs/guruh tanlagichlari bor', () => {
    renderFilters(studentState());
    expect(screen.getByRole('combobox', { name: /Fakultet/ })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: /Kurs/ })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: /Guruh/ })).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: /Turi/ })).toBeNull();
  });

  it("xodimlar bo'limida turi/bo'linma tanlagichlari bor", () => {
    renderFilters(staffState());
    expect(screen.getByRole('combobox', { name: /Turi/ })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: /Bo'linma/ })).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: /Fakultet/ })).toBeNull();
  });

  it('fakultet tanlovi `faculty` kalitiga yoziladi', () => {
    const { onChange } = renderFilters(studentState());
    fireEvent.change(screen.getByRole('combobox', { name: /Fakultet/ }), { target: { value: 'f1' } });
    expect(onChange).toHaveBeenCalledWith({ faculty: 'f1' });
  });

  it('kurs tanlovi `course` kalitiga yoziladi', () => {
    const { onChange } = renderFilters(studentState({ faculty: 'f1' }));
    fireEvent.change(screen.getByRole('combobox', { name: /Kurs/ }), { target: { value: '1' } });
    expect(onChange).toHaveBeenCalledWith({ course: '1' });
  });

  it("bo'linma turi `unitKind` kalitiga yoziladi", () => {
    const { onChange } = renderFilters(staffState());
    fireEvent.change(screen.getByRole('combobox', { name: /Turi/ }), { target: { value: 'kafedra' } });
    expect(onChange).toHaveBeenCalledWith({ unitKind: 'kafedra' });
  });

  it("bo'linma `unit` kalitiga yoziladi", () => {
    const { onChange } = renderFilters(staffState({ unitKind: 'kafedra' }));
    fireEvent.change(screen.getByRole('combobox', { name: /Bo'linma/ }), { target: { value: 'u1' } });
    expect(onChange).toHaveBeenCalledWith({ unit: 'u1' });
  });

  it('"Tozalash" sahifaning o\'z tiklashini chaqiradi (URL holati bilan)', () => {
    const { onReset, onChange } = renderFilters(studentState({ faculty: 'f1' }));
    screen.getByRole('button', { name: /Tozalash/ }).click();
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('filtr qo\'yilmaganda "Tozalash" chiqmaydi', () => {
    renderFilters(studentState());
    expect(screen.queryByRole('button', { name: /Tozalash/ })).toBeNull();
  });
});

describe('Excel eksport manzili', () => {
  it('barcha filtrlarni query\'ga o\'tkazadi', () => {
    const state = studentState({ faculty: 'f1', course: '2', group: '101-guruh', q: 'Ali', from: '2026-09-01', to: '2026-09-19' });
    const url = hisobotPaths.export(state, 'davomat');
    expect(url).toContain('/api/hisobot/export.xlsx');
    expect(url).toContain('kind=talaba');
    expect(url).toContain('from=2026-09-01');
    expect(url).toContain('to=2026-09-19');
    expect(url).toContain('criterion=davomat');
    expect(url).toContain('faculty=f1');
    expect(url).toContain('course=2');
    expect(url).toContain('q=Ali');
  });

  it("bo'sh filtrlar query'ga tushmaydi", () => {
    const url = hisobotPaths.export(studentState(), 'davomat');
    expect(url).not.toContain('faculty=');
    expect(url).not.toContain('course=');
    expect(url).not.toContain('unit=');
    expect(url).not.toContain('q=');
  });

  it("faqat probeldan iborat qidiruv eksportga tushmaydi", () => {
    const url = hisobotPaths.export(studentState({ q: '   ' }), 'davomat');
    expect(url).not.toContain('q=');
  });

  it("xodimlar bo'limi `unit_kind`/`unit` yuboradi", () => {
    const url = hisobotPaths.export(staffState({ unitKind: 'kafedra', unit: 'u1' }), 'punktuallik');
    expect(url).toContain('kind=xodim');
    expect(url).toContain('unit_kind=kafedra');
    expect(url).toContain('unit=u1');
  });
});

describe("«Tozalash» yozilayotgan qidiruvni ham tozalaydi", () => {
  it('debounce hali tugamagan matn tozalashdan keyin qaytib kelmaydi', async () => {
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      const onReset = vi.fn();
      // `state.q` bo'sh: foydalanuvchi endigina yozdi, 350 ms hali o'tmagan.
      render(<ReportFilters state={studentState()} options={OPTIONS} onChange={onChange} onReset={onReset} />);

      const box = screen.getByRole('searchbox', { name: /qidirish/i });
      fireEvent.change(box, { target: { value: 'Ali' } });
      // Debounce tugamasidan "Tozalash" bosiladi.
      fireEvent.click(screen.getByRole('button', { name: /Tozalash/ }));
      vi.advanceTimersByTime(1000);

      expect(onReset).toHaveBeenCalledTimes(1);
      // Tozalangandan keyin qidiruv qayta qo'llanmasligi kerak.
      expect(onChange).not.toHaveBeenCalledWith({ q: 'Ali' });
      expect((box as HTMLInputElement).value).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });
});
