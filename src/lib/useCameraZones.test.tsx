import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

const get = vi.fn();

vi.mock('./apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('./apiClient')>();
  return { ...original, api: { ...original.api, get: (...args: unknown[]) => get(...args) } };
});
vi.mock('./auth', () => ({ useAuth: () => ({ token: 'tok' }) }));

import { useCameraZones } from './useCameraZones';

/** Zona (xona) ro'yxati kameralardan yig'iladi, ya'ni kamera qo'shilsa
 *  yoki o'chirilsa o'zgaradi. Ilgari hook'da `reload` yo'q edi va
 *  o'zgarish faqat varaqni to'liq qayta yuklagandan keyin ko'rinardi. */
describe('useCameraZones', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("reload ro'yxatni qaytadan oladi", async () => {
    get
      .mockResolvedValueOnce([{ zone: '101-xona', cameraCount: 1 }])
      .mockResolvedValueOnce([
        { zone: '101-xona', cameraCount: 1 },
        { zone: '202-xona', cameraCount: 2 },
      ]);

    const { result } = renderHook(() => useCameraZones());
    await waitFor(() => expect(result.current.zones).toHaveLength(1));

    // Boshqa joyda yangi xonali kamera qo'shildi.
    await act(async () => {
      result.current.reload();
    });

    await waitFor(() => expect(result.current.zones.map((z) => z.zone)).toEqual(['101-xona', '202-xona']));
    expect(get).toHaveBeenCalledTimes(2);
  });
});
