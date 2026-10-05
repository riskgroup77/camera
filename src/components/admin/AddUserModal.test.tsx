// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

/**
 * QA: yangi foydalanuvchi oynasi.
 *
 * Ikki xato tuzatildi:
 *  1) "Bekor qilish" dan keyin oyna qayta ochilganda eski login/parol
 *     maydonlarda turib qolardi;
 *  2) yozilgan ma'lumot hech nima so'ramasdan yo'qolardi.
 */

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin' }) }));

import AddUserModal from './AddUserModal';

function open(props: Partial<{ open: boolean; onClose: () => void }> = {}) {
  return render(<AddUserModal open onClose={props.onClose ?? (() => {})} onAdd={() => {}} {...props} />);
}

describe('AddUserModal', () => {
  it('qayta ochilganda maydonlar tozalanadi', () => {
    const { rerender } = open();
    const loginInput = screen.getByPlaceholderText('a.alimov') as HTMLInputElement;
    fireEvent.change(loginInput, { target: { value: 'eski.login' } });
    expect((screen.getByPlaceholderText('a.alimov') as HTMLInputElement).value).toBe('eski.login');

    rerender(<AddUserModal open={false} onClose={() => {}} onAdd={() => {}} />);
    rerender(<AddUserModal open onClose={() => {}} onAdd={() => {}} />);

    expect((screen.getByPlaceholderText('a.alimov') as HTMLInputElement).value).toBe('');
  });

  it("to'ldirilgan oyna darhol yopilmaydi — avval tasdiq so'raydi", () => {
    const onClose = vi.fn();
    open({ onClose });
    fireEvent.change(screen.getByPlaceholderText('a.alimov'), { target: { value: 'a.alimov' } });

    fireEvent.click(screen.getByRole('button', { name: 'Bekor qilish' }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(/o'chib ketadi/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Ha, yopilsin/ }));
    expect(onClose).toHaveBeenCalled();
  });

  it("bo'sh oyna tasdiqsiz yopiladi", () => {
    const onClose = vi.fn();
    open({ onClose });
    fireEvent.click(screen.getByRole('button', { name: 'Bekor qilish' }));
    expect(onClose).toHaveBeenCalled();
  });
});
