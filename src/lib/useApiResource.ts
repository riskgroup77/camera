import { useCallback, useEffect, useState } from 'react';
import { ApiError, api, isAbortError } from './apiClient';
import { useAuth } from './auth';

/** Sahifalanmagan bitta GET uchun: yuklanish, xato va qayta yuklash.
 *
 * `useServerPage` ro'yxatlar uchun (sahifalash, debounce, kesh), bu esa
 * bitta obyekt uchun — masalan hisobot kriteriyalari yoki bitta odam
 * kesimi. Har sahifa buni o'z effekti bilan qayta yozib chiqmasin degan
 * maqsadda ajratilgan; eskirgan so'rov AbortController bilan bekor
 * qilinadi, aks holda tez almashtirilgan filtrlarda kech kelgan javob
 * yangisini bosib ketardi. */
export function useApiResource<T>(path: string | null) {
  const { token } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!path || !token) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    api
      .get<T>(path, token, { signal: controller.signal })
      .then((res) => {
        setData(res);
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Ma'lumotni yuklab bo'lmadi — ulanishni tekshiring",
        );
      })
      // Bekor qilingan so'rovning `finally`si yangisidan keyin kelardi —
      // shunda yangi so'rov hali ketayotgan bo'lsa ham "yuklanmoqda" o'chib,
      // ekran bir zumda "bo'sh" ko'rinardi.
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, token, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, loading, error, reload };
}
