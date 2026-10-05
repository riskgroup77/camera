import { describe, expect, it, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EnrollmentRegisterForm from './EnrollmentRegisterForm';
import * as enrollment from '../../lib/enrollment';

afterEach(() => vi.restoreAllMocks());

function setup(overrides: Partial<Parameters<typeof EnrollmentRegisterForm>[0]> = {}) {
  vi.spyOn(enrollment, 'listEnrollmentFaculties').mockResolvedValue([]);
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(<EnrollmentRegisterForm pinfl="30302654150047" onSubmit={onSubmit} onCancel={onCancel} {...overrides} />);
  return { onSubmit, onCancel };
}

const submitButton = () => screen.getByRole('button', { name: /Ro'yxatdan o'tish/ });

describe('EnrollmentRegisterForm', () => {
  it("faqat bo'sh joydan iborat maydonlar bilan yuborib bo'lmaydi", () => {
    const { onSubmit } = setup();

    fireEvent.change(screen.getByLabelText(/F.I.SH./), { target: { value: '   ' } });
    fireEvent.change(screen.getByLabelText(/Guruh/), { target: { value: '   ' } });

    expect(submitButton()).toBeDisabled();
    fireEvent.click(submitButton());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("qirqilgan ism uzunligi tekshiriladi — ' a ' o'tmaydi", () => {
    const { onSubmit } = setup();

    fireEvent.change(screen.getByLabelText(/F.I.SH./), { target: { value: ' a ' } });
    fireEvent.change(screen.getByLabelText(/Guruh/), { target: { value: '301-guruh' } });

    expect(submitButton()).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("to'g'ri ma'lumot qirqilgan holda uzatiladi", () => {
    const { onSubmit } = setup();

    fireEvent.change(screen.getByLabelText(/F.I.SH./), { target: { value: '  Aliyev Vali  ' } });
    fireEvent.change(screen.getByLabelText(/Guruh/), { target: { value: ' 301-guruh ' } });
    fireEvent.click(submitButton());

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ fullName: 'Aliyev Vali', groupOrPosition: '301-guruh', pinfl: '30302654150047' }),
    );
  });

  it("so'rov ketayotganda ikkala tugma ham bosilmaydi", () => {
    setup({ submitting: true, initialGroup: '301-guruh' });

    expect(screen.getByRole('button', { name: /Saqlanmoqda/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Boshqa raqam bilan/ })).toBeDisabled();
  });
});
