import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, isAbortError } from '../../lib/apiClient';

export interface Loader<T> {
  data: T | null;
  /** Birinchi yuklanish (ma'lumot hali yo'q). */
  loading: boolean;
  /** Fon yangilanishi (ma'lumot bor, yangisi kelmoqda). */
  refreshing: boolean;
  error: string | null;
  reload: () => void;
}

/** Bitta so'rov: `key` o'zgarganda qayta yuklaydi, eski so'rovni bekor
 *  qiladi. `refreshMs` — devor ekrani uchun fon yangilanishi (skeletsiz).
 *  `key === null` — so'rov yuborilmaydi. */
export function useLoader<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  options: {
    refreshMs?: number;
    /** Bir guruhdagi kalitlar orasida (masalan faqat davr o'zgarsa) eski
     *  ma'lumot yangisi kelguncha ko'rinib turadi — skelet miltillamaydi. */
    group?: string;
  } = {},
): Loader<T> {
  const [data, setData] = useState<T | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [loadedGroup, setLoadedGroup] = useState<string | undefined>(undefined);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  const groupRef = useRef(options.group);
  groupRef.current = options.group;

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setPending(true);
    setError(null);
    loadRef
      .current(controller.signal)
      .then((result) => {
        setData(result);
        setLoadedKey(key);
        setLoadedGroup(groupRef.current);
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Ma'lumotni yuklab bo'lmadi — ulanishni tekshiring");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [key, nonce]);

  const { refreshMs } = options;
  useEffect(() => {
    if (!refreshMs || key === null) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') setNonce((n) => n + 1);
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const keepPrevious = options.group !== undefined && loadedGroup === options.group;
  const stale = loadedKey !== key && !keepPrevious;
  return {
    data: stale ? null : data,
    loading: key !== null && stale && !error,
    refreshing: pending && !stale,
    // Fon yangilanishidagi xato eski ma'lumotni yashirmaydi — sahifa
    // xatoni faqat `data` yo'q bo'lganda ko'rsatadi.
    error: pending ? null : error,
    reload,
  };
}
