// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const post = vi.fn(async () => undefined as unknown);
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return { ...original, api: { ...original.api, post: (...args: unknown[]) => post(...(args as [])) } };
});

import { ApiError } from '../../lib/apiClient';
import ResetPasswordPage from './ResetPasswordPage';

function renderAt(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/parolni-tiklash${search}`]}>
      <ResetPasswordPage />
    </MemoryRouter>,
  );
}

function fill(password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText(/Yangi parol/i), { target: { value: password } });
  fireEvent.change(screen.getByLabelText(/Parolni tasdiqlang/i), { target: { value: confirm } });
}

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    post.mockReset();
    post.mockImplementation(async () => undefined as unknown);
  });

  it("muddati tugagan havolada (400) formani emas, tushuntirish ekranini ko'rsatadi", async () => {
    post.mockImplementation(async () => { throw new ApiError(400, 'Havola yaroqsiz yoki muddati tugagan'); });
    renderAt('?token=abc');
    fill('parol12345', 'parol12345');
    fireEvent.click(screen.getByRole('button', { name: /Parolni saqlash/i }));

    await waitFor(() => expect(screen.getByText(/Havola muddati tugagan/i)).toBeTruthy());
    // Yangi havola so'rash yo'li ko'rsatilgan bo'lishi shart.
    expect(screen.getByText(/Parolni unutdingizmi/i)).toBeTruthy();
    expect(screen.queryByLabelText(/Parolni tasdiqlang/i)).toBeNull();
  });

  it("429 da 'qayta urinib ko'ring' deb tushuntiradi, raqam bilan emas", async () => {
    post.mockImplementation(async () => { throw new ApiError(429, "So'rov muvaffaqiyatsiz tugadi (429)"); });
    renderAt('?token=abc');
    fill('parol12345', 'parol12345');
    fireEvent.click(screen.getByRole('button', { name: /Parolni saqlash/i }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/bir daqiqadan so'ng/i));
  });

  it('tasdiq xatosi parol to\'g\'rilangach darhol yo\'qoladi', async () => {
    renderAt('?token=abc');
    fill('parol12345', 'parol1');
    fireEvent.click(screen.getByRole('button', { name: /Parolni saqlash/i }));
    expect(screen.getByText(/Parollar mos kelmadi/i)).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Parolni tasdiqlang/i), { target: { value: 'parol12345' } });
    await waitFor(() => expect(screen.queryByText(/Parollar mos kelmadi/i)).toBeNull());
  });

  it('parolni ko\'rsatish tugmasi ikkala maydonni ochadi', () => {
    renderAt('?token=abc');
    fireEvent.click(screen.getByRole('button', { name: /Parolni ko'rsatish/i }));
    expect(screen.getByLabelText(/Yangi parol/i).getAttribute('type')).toBe('text');
    expect(screen.getByLabelText(/Parolni tasdiqlang/i).getAttribute('type')).toBe('text');
  });

  it("token bo'lmasa so'rov umuman yuborilmaydi", () => {
    renderAt('');
    expect(screen.getByText(/Havola yaroqsiz/i)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });
});
