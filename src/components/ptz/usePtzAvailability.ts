import { useEffect, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { ptzApi } from '../../lib/ptzApi';

/** Kamera holati (PTZ yoqilganmi) — sahifa umrida qayta-qayta so'ramaslik
 * uchun qisqa kesh: videodevorda bitta katakni kattalashtirib-kichraytirish
 * har safar so'rov yubormasin. */
const TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { enabled: boolean; at: number }>();

/** Joriy foydalanuvchi shu kamerani PTZ bilan boshqara oladimi.
 *
 * `knownEnabled` — kamera ma'lumotida PTZ maydoni bo'lsa (admin ro'yxati
 * CameraConfig.ptzEnabled). Ochiq ro'yxat (CameraFeed) uni qaytarmasa
 * `undefined` keladi va holat GET /api/cameras/{id}/ptz dan so'raladi —
 * faqat `controlPtz` huquqi borlarda, ya'ni boshqalar uchun so'rov umuman
 * ketmaydi. */
export function usePtzAvailability(cameraId: string | null | undefined, knownEnabled?: boolean): boolean {
  const { role } = useAuth();
  const { can } = usePermissions();
  const allowed = can('controlPtz', role);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    if (!cameraId || !allowed || knownEnabled === false) {
      setEnabled(false);
      return;
    }
    if (knownEnabled === true) {
      setEnabled(true);
      return;
    }
    const cached = cache.get(cameraId);
    if (cached && Date.now() - cached.at < TTL_MS) {
      setEnabled(cached.enabled);
      return;
    }
    let cancelled = false;
    setEnabled(false);
    ptzApi
      .status(cameraId)
      .then((status) => {
        const value = status.enabled && Boolean(status.protocol);
        cache.set(cameraId, { enabled: value, at: Date.now() });
        if (!cancelled) setEnabled(value);
      })
      .catch(() => {
        /* holatni bilmasak — panel ko'rsatilmaydi */
      });
    return () => {
      cancelled = true;
    };
  }, [cameraId, allowed, knownEnabled]);

  return enabled;
}

/** Kamera sozlamasi saqlanganda keshni tozalash (CameraConfigDetailModal). */
export function forgetPtzAvailability(cameraId: string): void {
  cache.delete(cameraId);
}
