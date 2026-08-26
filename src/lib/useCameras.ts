import { useEffect, useState } from 'react';
import { api, fetchAllPages } from './apiClient';
import { useAuth } from './auth';
import type { CameraConfig } from '../types';

/** Canonical, live camera list — used anywhere a form needs to pick a
 * camera by id (dars jadvali, taqiqlangan zona). Only 'faol' cameras are
 * fetched since a scheduled lesson/zone check needs a real stream to sweep
 * (see app/jobs/teacher_punctuality_ai.py / app/jobs/zone_entry_ai.py). */
export function useCameras() {
  const { token } = useAuth();
  const [cameras, setCameras] = useState<CameraConfig[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    fetchAllPages<CameraConfig>('/api/cameras', token, { status: 'faol' })
      .then((items) => {
        if (!cancelled) setCameras(items);
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
  }, [token]);

  return { cameras, loading };
}
