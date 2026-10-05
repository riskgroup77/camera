import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { CameraFeed } from '../../types';

const camera = (id: string, name: string): CameraFeed => ({
  id,
  name,
  building: '1-Bino',
  zone: '101-xona',
  status: 'live',
  streamUrl: `https://cam.example/s0/${id}/index.m3u8`,
  floor: 1,
});

let feed: () => Promise<CameraFeed[]> = async () => [camera('cam-1', 'Kamera 1')];

vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return { ...original, fetchAllPages: vi.fn(() => feed()) };
});
vi.mock('../LiveVideoPlayer', () => ({ default: () => <div data-testid="player" /> }));

import { CamerasPanel } from './CamerasPanel';

/** So'rov (va undan keyingi effektlar) tugashini kutish. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** Situatsion markaz ekrani (/markaz-ekran) kameralarni manzildagi
 *  `?cameras=` ro'yxatidan oladi. Sozlamalarda o'chirilgan kamera u
 *  yerda abadiy qolib, panelda "o'lik" katak bo'lib turardi. */
describe('CamerasPanel — sozlamadagi kamera ro\'yxatini tozalash', () => {
  beforeEach(() => {
    feed = async () => [camera('cam-1', 'Kamera 1')];
  });

  it("endi mavjud bo'lmagan kamera sozlamadan olib tashlanadi", async () => {
    const onPrune = vi.fn();
    render(<CamerasPanel ids={['cam-1', 'cam-yoq']} onAvailability={() => {}} onPrune={onPrune} />);
    await waitFor(() => expect(onPrune).toHaveBeenCalledWith(['cam-1']));
    expect(await screen.findByText('Kamera 1')).toBeInTheDocument();
  });

  it("xato yoki bo'sh javobda sozlama tegilmaydi", async () => {
    // Tarmoq xatosi "kamera o'chirilgan" degani emas.
    const onError = vi.fn();
    feed = async () => Promise.reject(new Error('tarmoq'));
    const errorView = render(<CamerasPanel ids={['cam-1']} onAvailability={() => {}} onPrune={onError} />);
    await settle();
    expect(errorView.queryByTestId('player')).toBeNull();
    expect(onError).not.toHaveBeenCalled();

    // Bo'sh javob ham "hamma kamera o'chirilgan" degani emas.
    const onEmpty = vi.fn();
    feed = async () => [];
    render(<CamerasPanel ids={['cam-1']} onAvailability={() => {}} onPrune={onEmpty} />);
    await settle();
    expect(onEmpty).not.toHaveBeenCalled();
  });
});
