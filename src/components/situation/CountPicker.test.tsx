import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import CountPicker from './CountPicker';

const options = [
  { value: 'DI-2301', label: 'DI-2301', present: 20, absent: 3, noData: 2 },
  { value: 'DI-2302', label: 'DI-2302', present: 15, absent: 9, noData: 0 },
];

describe('CountPicker', () => {
  it('ochilganda har guruh yonida kelgan/kelmagan/ma’lumotsiz sonlari, qidiruv va tanlash', () => {
    const onChange = vi.fn();
    render(<CountPicker label="Guruh" value="" onChange={onChange} options={options} />);
    fireEvent.click(screen.getByRole('button', { name: /Guruh/ }));
    const row = screen.getByRole('option', { name: /DI-2301/ });
    expect(row.textContent).toContain('20');
    expect(row.textContent).toContain('3');
    fireEvent.change(screen.getByLabelText('Guruh — qidirish'), { target: { value: '2302' } });
    expect(screen.queryByRole('option', { name: /DI-2301/ })).toBeNull();
    fireEvent.click(screen.getByRole('option', { name: /DI-2302/ }));
    expect(onChange).toHaveBeenCalledWith('DI-2302');
  });
});
