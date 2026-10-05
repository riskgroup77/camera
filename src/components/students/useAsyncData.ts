import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, isAbortError } from '../../lib/apiClient';

export interface AsyncData<T> {
  data: T | null;
  error: string | null;
  /** Birinchi yuklanish (ko'rsatiladigan ma'lumot hali yo'q). */
  loading: boolean;
  /** Fonda yangilanmoqda (eski ma'lumot ko'rinib turibdi). */
  refreshing: boolean;
  /** Oxirgi muvaffaqiyatli javob vaqti. */
  updatedAt: Date | null;
  reload: () => void;
  /** Mahalliy o'zgartirish (jonli xabar kelganda). */
  mutate: (update: (current: T) => T) => void;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return "Ma'lumotni yuklab bo'lmadi — ulanishni tekshiring";
}

/**
 * Bitta obyektni yuklash: eskirgan so'rov bekor qilinadi, sana/filtr
 * o'zgarganda eski ma'lumot yangisi kelguncha ko'rinib turadi (sahifa
 * "sakramaydi"), `identity` o'zgarsa (boshqa guruh/odam) — tozalanadi.
 * `refreshMs` — devor ekrani uchun fonda davriy yangilash (yashirin
 * tabda to'xtaydi).
 */
export function useAsyncData<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
  options: { identity?: string; refreshMs?: number } = {},
): AsyncData<T> {
  const { identity = '', refreshMs } = options;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [state, setState] = useState<{ data: T | null; identity: string; updatedAt: Date | null }>({
    data: null,
    identity,
    updatedAt: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(Boolean(key));
  const [nonce, setNonce] = useState(0);

  // Boshqa obyektga o'tildi — eski ma'lumot ko'rsatilmaydi.
  const data = state.identity === identity ? state.data : null;

  useEffect(() => {
    if (!key) {
      setPending(false);
      return;
    }
    const controller = new AbortController();
    setPending(true);
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setState({ data: result, identity, updatedAt: new Date() });
        setError(null);
        setPending(false);
      })
      .catch((err: unknown) => {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(errorText(err));
        setPending(false);
      });
    return () => controller.abort();
  }, [key, identity, nonce]);

  useEffect(() => {
    if (!refreshMs || !key) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') setNonce((n) => n + 1);
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const mutate = useCallback(
    (update: (current: T) => T) =>
      setState((prev) => (prev.data === null ? prev : { ...prev, data: update(prev.data) })),
    [],
  );

  return {
    data,
    error: data === null || !pending ? error : null,
    loading: data === null && pending,
    refreshing: data !== null && pending,
    updatedAt: state.updatedAt,
    reload,
    mutate,
  };
}
