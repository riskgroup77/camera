import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const { candidates, plan, mergeTwo } = vi.hoisted(() => {
  const card = (id: string, fullName: string, extra: Record<string, unknown> = {}) => ({
    id, fullName, groupOrPosition: '3-kurs, TPI-423', faculty: 'Tibbiy profilaktika', active: true,
    biometricsStatus: 'yoq', allAngles: false, hasPinfl: false, hemisLinked: false, selfRegistered: false,
    attendance: 0, lessons: 0, createdAt: null, photoUrl: null, ...extra,
  });
  const old = card('old', 'Mamajonova Dilbarxon Olimjon qizi', {
    active: false, biometricsStatus: 'tasdiqlangan', allAngles: true, hasPinfl: true,
  });
  const hemis = card('new', 'Kenjayeva Dilbarxon Olimjon qizi', { hemisLinked: true, attendance: 3 });
  const plan = {
    keep: old, remove: hemis, applied: false, moved: {},
    result: { fullName: hemis.fullName, groupOrPosition: hemis.groupOrPosition, faculty: hemis.faculty, active: true,
      biometricsStatus: 'tasdiqlangan', allAngles: true, hasPinfl: true, hemisLinked: true, attendance: 3 },
  };
  return { candidates: [old], plan, mergeTwo: vi.fn() };
});

vi.mock('../../lib/mergeApi', () => ({
  getMergeCandidates: vi.fn().mockResolvedValue(candidates),
  mergeTwo,
}));

import { ToastProvider } from '../../ui';
import MergePeopleModal from './MergePeopleModal';

describe('MergePeopleModal', () => {
  it("familiyasi o'zgargan, faol bo'lmagan klonni tanlab natijani ko'rsatadi va birlashtiradi", async () => {
    mergeTwo.mockImplementation((_a: string, _b: string, apply: boolean) => Promise.resolve({ ...plan, applied: apply }));
    const onMerged = vi.fn();
    render(
      <ToastProvider>
        <MergePeopleModal person={{ id: 'new', fullName: 'Kenjayeva Dilbarxon Olimjon qizi' }} onClose={() => {}} onMerged={onMerged} />
      </ToastProvider>,
    );
    fireEvent.click(await screen.findByRole('button', { name: /Mamajonova Dilbarxon/ }));
    expect(await screen.findByText('Natija — bitta yozuv')).toBeInTheDocument();
    expect(screen.getByText(/Yuz tasdiqlangan \(3 tomonlama\)/)).toBeInTheDocument();
    expect(screen.getByText(/3 kunlik davomat saqlanadi/)).toBeInTheDocument();
    expect(mergeTwo).toHaveBeenLastCalledWith('new', 'old', false);

    fireEvent.click(screen.getByRole('button', { name: 'Birlashtirish' }));
    await waitFor(() => expect(onMerged).toHaveBeenCalled());
    expect(mergeTwo).toHaveBeenLastCalledWith('new', 'old', true);
  });

  it("server rad etsa (ikki xil JSHSHIR) — sababini ko'rsatadi, tugma o'chiq", async () => {
    const { ApiError } = await import('../../lib/apiClient');
    mergeTwo.mockRejectedValue(new ApiError(409, 'Ikki yozuvda ikki xil JSHSHIR — bular boshqa-boshqa odamlar'));
    render(
      <ToastProvider>
        <MergePeopleModal person={{ id: 'new', fullName: 'X' }} onClose={() => {}} onMerged={() => {}} />
      </ToastProvider>,
    );
    fireEvent.click(await screen.findByRole('button', { name: /Mamajonova Dilbarxon/ }));
    expect(await screen.findByText(/ikki xil JSHSHIR/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Birlashtirish' })).toBeDisabled();
  });
});
