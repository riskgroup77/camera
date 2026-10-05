import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAllPages } from '../../lib/apiClient';
import type { CameraFeed } from '../../types';

/** Videodevor uchun BARCHA kameralar (GET /api/public/cameras, sahifama-
 * sahifa, 500 tadan). Yuzlab kamera — bir necha yuz KB, bir martada
 * olinadi: yon paneldagi qidiruv/filtr va saqlangan ko'rinishlardagi
 * kameralarni id bo'yicha topish shu ro'yxatdan ishlaydi.
 *
 * Holat (jonli/oflayn) daqiqada bir yangilanadi, faqat varaq ko'rinib
 * turganda. Video havolalari imzolangan, lekin 6 soatlik oraliqda
 * o'zgarmaydi (camera-api/app/services/stream_links.py) — shuning uchun
 * yangilanish pleyerlarni qayta ulamaydi. */
const REFRESH_MS = 60_000;
/** Pleyer "havolam yaroqsiz" deganda ro'yxatni shundan tez-tez
 * so'ramaymiz. 16 ta katakning har biri xato berishi mumkin, shuning uchun
 * bu chegara bo'lmasa bitta uzilish ro'yxat so'rovlari toshqinini
 * keltirib chiqarardi. */
const STREAM_REFRESH_MIN_GAP_MS = 20_000;

export function useWallCameras() {
  const [cameras, setCameras] = useState<CameraFeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Oxirgi MUVAFFAQIYATLI va bo'sh bo'lmagan javobdagi identifikatorlar.
   * `null` — hali bunday javob yo'q (yuklanmoqda, xato yoki bo'sh
   * ro'yxat). Kataklarni tozalash faqat shu to'plam bilan qilinadi. */
  const [knownIds, setKnownIds] = useState<ReadonlySet<string> | null>(null);
  const inflight = useRef(false);
  const lastLoadAt = useRef(0);

  /** `showBusy` — foydalanuvchi "Yangilash" tugmasini bosgan: kutish
   * ko'rsatkichi chiqadi. Fon (daqiqalik) yangilanishi jimgina o'tadi,
   * aks holda tugma har daqiqada o'z-o'zidan aylanardi. */
  const load = useCallback(async (showBusy = false) => {
    if (showBusy) setLoading(true);
    // Allaqachon so'rov ketayotgan bo'lsa ikkinchisi yuborilmaydi, lekin
    // yuqoridagi `setLoading(true)` qoladi: ketayotgan so'rov tugaganda
    // `finally` uni o'chiradi, ya'ni tugma baribir "bosildi" deb ko'rinadi.
    if (inflight.current) return;
    inflight.current = true;
    lastLoadAt.current = Date.now();
    try {
      const items = await fetchAllPages<CameraFeed>('/api/public/cameras', undefined, {}, 500);
      setCameras(items);
      if (items.length > 0) setKnownIds(new Set(items.map((camera) => camera.id)));
      setError(null);
    } catch {
      // Eski ro'yxat (bo'lsa) qoladi — devor bir martalik tarmoq xatosidan
      // bo'shab qolmasin; xato alohida ko'rsatiladi.
      setError("Kameralar ro'yxatini yuklab bo'lmadi. Tarmoqni tekshiring yoki qayta kiring.");
    } finally {
      inflight.current = false;
      setLoading(false);
    }
  }, []);

  const reload = useCallback(() => load(true), [load]);

  /** Pleyer oqim manzilini yaroqsiz deb topdi (403 — imzo muddati tugagan,
   * 404 — yo'l yo'q). Imzolangan havola faqat shu ro'yxat bilan keladi,
   * shuning uchun tiklanishning YAGONA yo'li — ro'yxatni qayta olish.
   * Kutish ko'rsatkichisiz va chegaralangan tezlikda. */
  const refreshStreams = useCallback(() => {
    if (Date.now() - lastLoadAt.current < STREAM_REFRESH_MIN_GAP_MS) return;
    void load();
  }, [load]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  return { cameras, loading, error, knownIds, reload, refreshStreams };
}
