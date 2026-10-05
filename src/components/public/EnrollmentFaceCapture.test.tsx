import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import EnrollmentFaceCapture from './EnrollmentFaceCapture';

/** getUserMedia'ni almashtiradi va oldingi qiymatni tiklash uchun
 *  funksiya qaytaradi. */
function mockGetUserMedia(impl: () => Promise<MediaStream>) {
  const original = navigator.mediaDevices;
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(impl) },
  });
  return () => Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: original });
}

let restore: (() => void) | null = null;

beforeEach(() => {
  // jsdom'da video.play() yo'q.
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
});

afterEach(() => {
  restore?.();
  restore = null;
  vi.restoreAllMocks();
});

function fakeStream(onStop?: () => void): MediaStream {
  const track = { stop: vi.fn(() => onStop?.()), kind: 'video' } as unknown as MediaStreamTrack;
  return { getTracks: () => [track] } as unknown as MediaStream;
}

describe('EnrollmentFaceCapture — kamera xatolari', () => {
  it('ruxsat berilmagani va kamera bandligi turli xabar beradi', async () => {
    restore = mockGetUserMedia(() => Promise.reject(new DOMException('denied', 'NotAllowedError')));
    const { unmount } = render(<EnrollmentFaceCapture onSubmit={() => {}} />);
    expect(await screen.findByText(/Kameraga ruxsat berilmadi/)).toBeInTheDocument();
    unmount();
    restore();

    restore = mockGetUserMedia(() => Promise.reject(new DOMException('busy', 'NotReadableError')));
    render(<EnrollmentFaceCapture onSubmit={() => {}} />);
    expect(await screen.findByText(/boshqa dastur band qilgan/)).toBeInTheDocument();
  });

  it('kamera topilmagani alohida aytiladi', async () => {
    restore = mockGetUserMedia(() => Promise.reject(new DOMException('none', 'NotFoundError')));
    render(<EnrollmentFaceCapture onSubmit={() => {}} />);
    expect(await screen.findByText(/kamera topilmadi/i)).toBeInTheDocument();
  });

  it("«Qayta urinish» sahifani yangilamay kamerani qayta ochadi", async () => {
    let calls = 0;
    restore = mockGetUserMedia(() => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new DOMException('busy', 'NotReadableError'))
        : Promise.resolve(fakeStream());
    });
    render(<EnrollmentFaceCapture onSubmit={() => {}} />);

    fireEvent.click(await screen.findByRole('button', { name: /Qayta urinish/ }));

    await waitFor(() => expect(screen.queryByText(/Kamera ochilmadi/)).toBeNull());
    expect(calls).toBe(2);
  });

  it('sahifadan chiqilganda kamera treklari to‘xtatiladi', async () => {
    const stopped = vi.fn();
    restore = mockGetUserMedia(() => Promise.resolve(fakeStream(stopped)));
    const { unmount } = render(<EnrollmentFaceCapture onSubmit={() => {}} />);

    await screen.findByText(/1\/3/);
    unmount();
    await waitFor(() => expect(stopped).toHaveBeenCalled());
  });
});
