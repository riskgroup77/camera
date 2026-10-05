import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EnrollmentConsent from './EnrollmentConsent';
import * as enrollment from '../../lib/enrollment';
import { ApiError } from '../../lib/apiClient';
import type { ConsentText } from '../../lib/enrollment';

const TEXT: ConsentText = {
  version: 'v1',
  required: true,
  title: "Biometrik shaxsga doir ma'lumotlarni qayta ishlashga rozilik",
  controller: "Farg'ona JSSTI",
  sections: [
    { title: 'Qayta ishlash maqsadi', body: 'Davomat va xavfsizlik.' },
    { title: 'Sizning huquqlaringiz', body: 'Rozilikni qaytarib olish huquqi.' },
  ],
  statement: 'Men rozilik beraman.',
};

afterEach(() => vi.restoreAllMocks());

describe('EnrollmentConsent', () => {
  it('belgi qo‘yilmaguncha davom etib bo‘lmaydi, keyin consent=true uzatiladi', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockResolvedValue(TEXT);
    const onContinue = vi.fn();
    render(<EnrollmentConsent onContinue={onContinue} onBack={() => {}} />);

    const button = await screen.findByRole('button', { name: /skanerlashga o'tish/ });
    expect(button).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox'));
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onContinue).toHaveBeenCalledWith(true);
  });

  it('to‘liq matn ochiladi', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockResolvedValue(TEXT);
    render(<EnrollmentConsent onContinue={() => {}} onBack={() => {}} />);

    fireEvent.click(await screen.findByRole('button', { name: /To'liq matnni o'qish/ }));
    expect(screen.getByText('Sizning huquqlaringiz')).toBeInTheDocument();
    expect(screen.getByText('Rozilikni qaytarib olish huquqi.')).toBeInTheDocument();
  });

  it('ixtiyoriy bo‘lsa belgisiz ham davom etiladi (consent=false)', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockResolvedValue({ ...TEXT, required: false });
    const onContinue = vi.fn();
    render(<EnrollmentConsent onContinue={onContinue} onBack={() => {}} />);

    fireEvent.click(await screen.findByRole('button', { name: /skanerlashga o'tish/ }));
    expect(onContinue).toHaveBeenCalledWith(false);
  });

  it('matn yuklanmasa davom etish tugmasi yo‘q', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockRejectedValue(new Error('tarmoq'));
    render(<EnrollmentConsent onContinue={() => {}} onBack={() => {}} />);

    expect(await screen.findByText(/Rozilik matnini yuklab bo'lmadi/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /skanerlashga o'tish/ })).toBeNull();
  });

  it('server xatosining inglizcha matni ekranga chiqmaydi (5xx/422)', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockRejectedValue(new ApiError(500, 'Internal Server Error'));
    render(<EnrollmentConsent onContinue={() => {}} onBack={() => {}} />);

    expect(await screen.findByText(/Rozilik matnini yuklab bo'lmadi/)).toBeInTheDocument();
    expect(screen.queryByText(/Internal Server Error/)).toBeNull();
  });

  it('serverning 4xx dagi o‘zbekcha xabari esa ko‘rsatiladi', async () => {
    vi.spyOn(enrollment, 'fetchConsentText').mockRejectedValue(new ApiError(403, "Rozilik matni o'chirilgan"));
    render(<EnrollmentConsent onContinue={() => {}} onBack={() => {}} />);

    expect(await screen.findByText("Rozilik matni o'chirilgan")).toBeInTheDocument();
  });
});
