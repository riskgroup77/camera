// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

/**
 * QA: sinov xabari oynasi.
 *
 *  - `status` fonda yangilanganda (u har safar YANGI obyekt) foydalanuvchi
 *    yozgan raqam va matn jimgina o'chib ketardi;
 *  - tarmoq/server xatosi "Telefon raqami" maydoni tagida chiqib, raqam
 *    noto'g'ridek ko'rinardi.
 */

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin' }) }));

const sendTest = vi.fn();
vi.mock('../../lib/notificationsApi', async () => {
  const actual = await vi.importActual<typeof import('../../lib/notificationsApi')>('../../lib/notificationsApi');
  return { ...actual, notificationsApi: { ...actual.notificationsApi, sendTest: (...args: unknown[]) => sendTest(...args) } };
});

import TestMessageModal from './TestMessageModal';
import { ApiError } from '../../lib/apiClient';
import type { NotificationStatus } from '../../lib/notificationsApi';

function makeStatus(): NotificationStatus {
  return {
    telegramConfigured: true,
    telegramBotUsername: 'bot',
    telegramPollingEnabled: true,
    smsProvider: 'eskiz',
    smsConfigured: true,
    smsSender: '4546',
    parentArrivalEnabled: true,
    parentAbsenceEnabled: true,
    orgName: 'Test',
  };
}

const recipientInput = () => screen.getByPlaceholderText(/123456789/) as HTMLInputElement;

describe('TestMessageModal', () => {
  it("status fonda yangilansa kiritilgan ma'lumot saqlanadi", () => {
    const { rerender } = render(<TestMessageModal open status={makeStatus()} onClose={() => {}} onSent={() => {}} />);

    fireEvent.change(recipientInput(), { target: { value: '123456789' } });
    expect(recipientInput().value).toBe('123456789');

    // useApiResource har javobda yangi obyekt beradi — bu o'chirib yubormasligi kerak.
    rerender(<TestMessageModal open status={makeStatus()} onClose={() => {}} onSent={() => {}} />);

    expect(recipientInput().value).toBe('123456789');
  });

  it("yuborish xatosi maydon xatosi sifatida emas, alohida ogohlantirish bo'lib chiqadi", async () => {
    sendTest.mockRejectedValueOnce(new ApiError(502, 'Telegram javob bermadi'));
    render(<TestMessageModal open status={makeStatus()} onClose={() => {}} onSent={() => {}} />);

    fireEvent.change(recipientInput(), { target: { value: '123456789' } });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: /Yuborish/i }).closest('form') ?? document.forms[0]);
    });

    const alert = screen.getByText('Telegram javob bermadi');
    expect(alert).toBeTruthy();
    // Maydon xato holatiga tushmaydi.
    expect(recipientInput().getAttribute('aria-invalid')).not.toBe('true');
  });

  it("raqam o'zgartirilsa oldingi natija eskiradi va yo'qoladi", async () => {
    sendTest.mockResolvedValueOnce({ ok: true, error: null });
    render(<TestMessageModal open status={makeStatus()} onClose={() => {}} onSent={() => {}} />);

    fireEvent.change(recipientInput(), { target: { value: '123456789' } });
    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: /Yuborish/i }).closest('form') ?? document.forms[0]);
    });
    expect(screen.getByText(/Xabar yuborildi/i)).toBeTruthy();

    fireEvent.change(recipientInput(), { target: { value: '987654321' } });
    expect(screen.queryByText(/Xabar yuborildi/i)).toBeNull();
  });
});
