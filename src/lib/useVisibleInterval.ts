import { useEffect, useRef } from 'react';

/** Sahifa ko'rinib turganda `delayMs`da bir marta `callback`ni chaqiradi.
 *
 *  Yorliq (tab) fonga o'tsa taymer to'xtaydi — brauzer orqasida turgan
 *  sahifa serverni bekorga qiynamaydi; qaytib ko'ringanda darhol bir marta
 *  yangilanadi, shunda ekrandagi ma'lumot eskirmaydi.
 *
 *  `delayMs === null` — taymer umuman ishlamaydi (o'chirilgan holat).
 *  `callback` har renderda yangilansa ham taymer qayta qurilmaydi. */
export function useVisibleInterval(callback: () => void, delayMs: number | null): void {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (delayMs === null) return;
    const run = () => saved.current();
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') run();
    }, delayMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') run();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [delayMs]);
}
