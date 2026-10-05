import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, isAbortError } from '../../lib/apiClient';

export interface LiveResource<T> {
  data: T | null;
  /** Birinchi yuklanish (ma'lumot hali yo'q). Fondagi yangilanishda false. */
  loading: boolean;
  /** Oxirgi so'rov xatosi. Eski ma'lumot bo'lsa ham saqlanadi (ekranda qoladi). */
  error: string | null;
  /** Oxirgi muvaffaqiyatli javob vaqti (ms). */
  updatedAt: number | null;
  /** So'rov ketmoqda (fondagi yangilanish ham). */
  fetching: boolean;
  reload: () => void;
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Bu ma'lumotni ko'rish uchun huquq yetarli emas";
    return err.message;
  }
  return "Ma'lumotni yuklab bo'lmadi — ulanishni tekshiring";
}

/** Devor ekrani uchun GET: `refreshKey` o'zgarganda jimgina qayta so'raydi —
 *  eski ma'lumot ekranda qoladi (skeleton qayta chiqmaydi, sahifa sakramaydi).
 *  `key` o'zgarsa (masalan sana) — ma'lumot tozalanadi va skeleton chiqadi.
 *  `key === null` — so'rov yuborilmaydi (huquq yo'q). */
export function useLiveResource<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  refreshKey: number,
): LiveResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(key));
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [fetching, setFetching] = useState(false);
  const [nonce, setNonce] = useState(0);
  const lastKey = useRef<string | null | undefined>(undefined);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!key) {
      lastKey.current = key;
      setData(null);
      setLoading(false);
      setError(null);
      setUpdatedAt(null);
      setFetching(false);
      return;
    }
    if (lastKey.current !== key) {
      lastKey.current = key;
      setData(null);
      setError(null);
      setLoading(true);
    }
    const controller = new AbortController();
    setFetching(true);
    fetcherRef
      .current(controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        setData(res);
        setError(null);
        setUpdatedAt(Date.now());
      })
      .catch((err) => {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(messageOf(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setFetching(false);
        }
      });
    return () => controller.abort();
  }, [key, refreshKey, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, updatedAt, fetching, reload };
}

/** Avtomatik yangilanish hisoblagichi: har `intervalMs`da va `bump()`da
 *  (realtime xabar — `debounceMs` ichida bir marta) oshadi. Sahifa
 *  yashirin bo'lsa taymer ishlamaydi, qayta ko'ringanda darhol yangilanadi. */
export function useRefreshTicker(intervalMs: number, enabled = true, debounceMs = 4_000) {
  const [tick, setTick] = useState(0);
  const debounceRef = useRef<number | null>(null);

  const refreshNow = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setTick((t) => t + 1);
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') setTick((t) => t + 1);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [intervalMs, enabled]);

  const bump = useCallback(() => {
    if (debounceRef.current !== null) return;
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      setTick((t) => t + 1);
    }, debounceMs);
  }, [debounceMs]);

  useEffect(
    () => () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    },
    [],
  );

  return { tick, bump, refreshNow };
}
