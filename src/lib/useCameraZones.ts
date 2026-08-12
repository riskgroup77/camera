import { useEffect, useState } from 'react';
import { api, buildQuery } from './apiClient';
import { useAuth } from './auth';

export interface CameraZone {
  zone: string;
  cameraCount: number;
}

/** Distinct room/zone names with how many cameras are already assigned to
 * each — a room routinely holds more than one camera (different angles),
 * so this backs the zone-name autocomplete in AddCameraModal (pick an
 * existing room instead of retyping/mistyping its name) and the zone
 * filter chips in CamerasZonesPage. */
export function useCameraZones(building?: string) {
  const { token } = useAuth();
  const [zones, setZones] = useState<CameraZone[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<CameraZone[]>(`/api/cameras/zones${buildQuery({ building })}`, token)
      .then((res) => {
        if (!cancelled) setZones(res);
      })
      .catch(() => {
        /* ulanish muvaffaqiyatsiz — bo'sh ro'yxat bilan davom etamiz */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, building]);

  return { zones, loading };
}
