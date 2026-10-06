import { todayInTashkent } from './uzDate';

/**
 * Qisqa muddatli GET javob keshi — Nazorat konsolida "Bugun" / "Kecha"
 * almashganda ma'lumot darhol chiqsin (2026-10-06: guruhlar ro'yxati har
 * bosishda internet orqali qayta yuklanardi).
 *
 * Bir xil kalit (URL) TTL ichida qayta so'ralmaydi; parallel so'rovlar
 * bitta va'dani bo'lishadi. Chaqiruvchining bekor qilishi (AbortSignal)
 * faqat O'ZINI to'xtatadi — umumiy so'rov tugaydi va keshga tushadi
 * (oldindan yuklash shu tufayli ishlaydi). Xato keshda qolmaydi.
 */

interface Entry {
  at: number;
  promise: Promise<unknown>;
}

const cache = new Map<string, Entry>();
const MAX_ENTRIES = 80;

/** Bugun — 15 s (server keshi bilan bir xil, jonli ma'lumot), o'tgan kun — 5 daqiqa. */
export function ttlForDate(date: string | undefined, today = todayInTashkent()): number {
  return date && date < today ? 5 * 60_000 : 15_000;
}

function abortError(): DOMException {
  return new DOMException('Bekor qilindi', 'AbortError');
}

function withSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener('abort', onAbort);
        reject(error);
      },
    );
  });
}

export function cachedRequest<T>(key: string, ttlMs: number, load: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  const now = Date.now();
  const hit = cache.get(key);
  let promise: Promise<T>;
  if (hit && now - hit.at < ttlMs) {
    promise = hit.promise as Promise<T>;
  } else {
    promise = load();
    cache.set(key, { at: now, promise });
    promise.catch(() => {
      if (cache.get(key)?.promise === promise) cache.delete(key);
    });
    while (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value as string);
  }
  return withSignal(promise, signal);
}

/** Oldindan yuklash: xatolar jim (keyin odatdagi so'rov qayta urinadi). */
export function prefetch(run: () => Promise<unknown>): void {
  run().catch(() => undefined);
}

export function clearResponseCache(): void {
  cache.clear();
}
