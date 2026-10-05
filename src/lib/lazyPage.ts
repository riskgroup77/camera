import { lazy, type ComponentType } from 'react';

const RELOAD_KEY = 'sahifa-bolagi-qayta-yuklangan';
const RELOAD_GUARD_MS = 30_000;

function readLastReload(): number {
  try {
    return Number(sessionStorage.getItem(RELOAD_KEY)) || 0;
  } catch {
    return 0;
  }
}

/**
 * React.lazy + deploydan keyin eskirgan JS bo'lagidan himoya.
 *
 * Deploy `rsync --delete` bilan eski hashli fayllarni o'chiradi. Kun bo'yi
 * ochiq turadigan ekran (monitoring, operator) keyin hali ochilmagan
 * sahifaga o'tsa, brauzer endi yo'q faylni so'raydi va sahifa xato beradi.
 * Shunda sahifa bir marta qayta yuklanadi — yangi index.html yangi fayl
 * nomlarini olib keladi. Haqiqiy tarmoq uzilishida cheksiz qayta yuklanish
 * bo'lmasligi uchun 30 soniyalik to'siq bor: undan keyin xato
 * ErrorBoundary'ga o'tadi.
 */
export function lazyPage<T extends ComponentType<object>>(factory: () => Promise<{ default: T }>) {
  return lazy(() =>
    factory().catch((error: unknown) => {
      if (Date.now() - readLastReload() > RELOAD_GUARD_MS) {
        try {
          sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
        } catch {
          /* storage yo'q — baribir bir marta qayta yuklaymiz */
        }
        window.location.reload();
        return new Promise<never>(() => {});
      }
      throw error;
    }),
  );
}
