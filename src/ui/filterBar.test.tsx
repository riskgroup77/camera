// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FilterBar } from './Toolbar';
import { filterActiveCount, isFilterActive, resetFilterFields, type FilterFieldEntry } from './filterFields';

const noop = () => {};

describe('filterActiveCount', () => {
  it("bo'sh qidiruv va standart tanlovlar — 0", () => {
    const fields: FilterFieldEntry[] = [
      { kind: 'search', value: '', onChange: noop },
      { kind: 'select', value: '', onChange: noop, options: [] },
    ];
    expect(filterActiveCount(fields)).toBe(0);
  });

  it("faqat probel yozilgan qidiruv faol emas (ilgari sahifalar har xil sanardi)", () => {
    expect(isFilterActive({ kind: 'search', value: '   ', onChange: noop })).toBe(false);
    expect(isFilterActive({ kind: 'search', value: ' a ', onChange: noop })).toBe(true);
  });

  it("'hammasi' qiymati bo'sh satr bo'lmasligi mumkin (inactiveValue)", () => {
    const all = { kind: 'select', value: 'all', onChange: noop, options: [], inactiveValue: 'all' } as const;
    expect(isFilterActive(all)).toBe(false);
    expect(isFilterActive({ ...all, value: 'yuzsiz' })).toBe(true);
  });

  it("shart bilan o'chirilgan maydonlar sanalmaydi", () => {
    const fields: FilterFieldEntry[] = [
      { kind: 'search', value: 'ali', onChange: noop },
      false,
      null,
      undefined,
      { kind: 'select', value: '3', onChange: noop, options: [] },
    ];
    expect(filterActiveCount(fields)).toBe(2);
  });

  it("custom maydon faolligini sahifa aytadi", () => {
    expect(filterActiveCount([{ kind: 'custom', render: null, active: true }])).toBe(1);
    expect(filterActiveCount([{ kind: 'custom', render: null }])).toBe(0);
  });
});

describe('resetFilterFields', () => {
  it("har bir maydonni standart holatiga qaytaradi", () => {
    const search = vi.fn();
    const select = vi.fn();
    const allSelect = vi.fn();
    const clear = vi.fn();
    resetFilterFields([
      { kind: 'search', value: 'ali', onChange: search },
      { kind: 'select', value: '3', onChange: select, options: [] },
      { kind: 'select', value: 'yuzsiz', onChange: allSelect, options: [], inactiveValue: 'all' },
      { kind: 'custom', render: null, active: true, onClear: clear },
      false,
    ]);
    expect(search).toHaveBeenCalledWith('');
    expect(select).toHaveBeenCalledWith('');
    expect(allSelect).toHaveBeenCalledWith('all');
    expect(clear).toHaveBeenCalledTimes(1);
  });

  it("onClear berilmagan custom maydon tozalanmaydi (xato bermaydi)", () => {
    expect(() => resetFilterFields([{ kind: 'custom', render: null, active: true }])).not.toThrow();
  });
});

describe('<FilterBar />', () => {
  it("faol filtr bo'lmasa Tozalash tugmasi yo'q", () => {
    render(<FilterBar fields={[{ kind: 'search', value: '', onChange: noop }]} />);
    expect(screen.queryByRole('button', { name: /Tozalash/ })).toBeNull();
  });

  it('faol filtrlar sonini tugmada ko\'rsatadi', () => {
    render(
      <FilterBar
        fields={[
          { kind: 'search', value: 'ali', onChange: noop },
          { kind: 'select', value: 'faol', onChange: noop, options: [{ value: 'faol', label: 'Faol' }] },
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: /Tozalash \(2\)/ })).toBeTruthy();
  });

  it("Tozalash har bir maydonni qaytaradi", async () => {
    const search = vi.fn();
    render(<FilterBar fields={[{ kind: 'search', value: 'ali', onChange: search }]} />);
    screen.getByRole('button', { name: /Tozalash/ }).click();
    expect(search).toHaveBeenCalledWith('');
  });

  it("inactiveValue bo'sh satrga o'giriladi (option ro'yxatida yo'q qiymat)", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        fields={[
          {
            kind: 'select',
            value: 'all',
            inactiveValue: 'all',
            onChange,
            ariaLabel: 'Filtr',
            placeholder: 'Hammasi',
            options: [{ value: 'yuzsiz', label: 'Yuzsiz' }],
          },
        ]}
      />,
    );
    const select = screen.getByRole('combobox', { name: 'Filtr' }) as HTMLSelectElement;
    // 'all' option'lar orasida yo'q — placeholder (bo'sh satr) tanlangan.
    expect(select.value).toBe('');
    expect(screen.queryByRole('button', { name: /Tozalash/ })).toBeNull();
  });

  it("bo'sh satr tanlanganda sahifaga inactiveValue qaytadi", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        fields={[
          {
            kind: 'select',
            value: 'yuzsiz',
            inactiveValue: 'all',
            onChange,
            ariaLabel: 'Filtr',
            placeholder: 'Hammasi',
            options: [{ value: 'yuzsiz', label: 'Yuzsiz' }],
          },
        ]}
      />,
    );
    const select = screen.getByRole('combobox', { name: 'Filtr' }) as HTMLSelectElement;
    expect(select.value).toBe('yuzsiz');
    screen.getByRole('button', { name: /Tozalash \(1\)/ }).click();
    expect(onChange).toHaveBeenCalledWith('all');
  });

  it('onReset berilsa maydonlar emas, o\'sha chaqiriladi', () => {
    const search = vi.fn();
    const onReset = vi.fn();
    render(<FilterBar onReset={onReset} fields={[{ kind: 'search', value: 'ali', onChange: search }]} />);
    screen.getByRole('button', { name: /Tozalash/ }).click();
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(search).not.toHaveBeenCalled();
  });
});
