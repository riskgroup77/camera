import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, REQUEST_TIMEOUT_MS, TIMEOUT_MESSAGE, api, isAbortError } from './apiClient';

/**
 * Qotib qolgan so'rov — cheksiz spinner.
 *
 * Backend qayta ishga tushayotganda (yoki VPN uzilganda) `fetch` javob
 * ham, xato ham bermasdan osilib qolardi: sahifa esa "yuklanmoqda"
 * holatida abadiy turardi — na sabab, na "Qayta urinish". Har bir
 * so'rovning vaqt chegarasi bor, va u tugaganda oddiy ApiError bo'ladi,
 * ya'ni ekranda xato holati va qayta urinish tugmasi chiqadi.
 */
describe('apiClient so\'rov vaqti chegarasi', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('javob bermagan so\'rovni tushunarli xato bilan tugatadi', async () => {
    // Hech qachon tugamaydigan fetch — faqat abort bilan yiqiladi.
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('The operation was aborted.', 'AbortError')),
            );
          }),
      ),
    );

    const promise = api.get('/api/events').catch((err: unknown) => err);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 10);
    const err = await promise;

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe(TIMEOUT_MESSAGE);
    // Bekor qilingan so'rov EMAS: chaqiruvchi uni jimgina yutib yubormasin.
    expect(isAbortError(err)).toBe(false);
  });

  it('chaqiruvchi o\'zi bekor qilgan so\'rov AbortError bo\'lib qoladi', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('The operation was aborted.', 'AbortError')),
            );
          }),
      ),
    );

    const controller = new AbortController();
    const promise = api.get('/api/events', null, { signal: controller.signal }).catch((err: unknown) => err);
    controller.abort();
    const err = await promise;

    expect(isAbortError(err)).toBe(true);
    expect(err).not.toBeInstanceOf(ApiError);
  });

  it('vaqtida kelgan javobda taymer so\'rovni buzmaydi', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"ok":true}', { status: 200 })));
    await expect(api.get<{ ok: boolean }>('/api/events')).resolves.toEqual({ ok: true });
  });
});
