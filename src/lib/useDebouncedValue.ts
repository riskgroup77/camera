import { useEffect, useState } from 'react';

/** Qiymat `delayMs` davomida o'zgarmasa, uni qaytaradi. Qidiruv maydonida
 *  har harf bosilganda serverga so'rov ketmasligi uchun. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    if (delayMs <= 0) {
      setDebounced(value);
      return;
    }
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
