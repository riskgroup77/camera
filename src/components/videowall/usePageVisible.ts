import { useEffect, useState } from 'react';

/** Varaq (yoki alohida oyna) ko'rinib turibdimi.
 *
 * Fonga o'tgandan keyin `graceMs` o'tsa — false: videodevor shunda barcha
 * HLS pleyerlarni yopadi (brauzer dekoderi va MediaMTX o'quvchilari
 * bo'shaydi). Qisqa almashishda (bir-ikki soniya boshqa varaqqa o'tib
 * qaytish) pleyerlar qayta ulanib "miltillamasligi" uchun kechikish bor.
 * Qaytib kelganda darhol true. */
export function usePageVisible(graceMs = 15_000): boolean {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden');

  useEffect(() => {
    let timer: number | undefined;
    const onChange = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
      if (document.visibilityState === 'hidden') {
        timer = window.setTimeout(() => setVisible(false), graceMs);
      } else {
        setVisible(true);
      }
    };
    document.addEventListener('visibilitychange', onChange);
    return () => {
      document.removeEventListener('visibilitychange', onChange);
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [graceMs]);

  return visible;
}
