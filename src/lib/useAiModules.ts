import { useEffect, useState } from 'react';
import { api } from './apiClient';
import { useAuth } from './auth';
import type { AIModule } from '../types';

/** Canonical, live AI-module registry — backs CameraModulesModal.tsx's
 * per-camera exclusion checklist. Mirrors useBuildings.ts/useFaculties.ts. */
export function useAiModules() {
  const { token } = useAuth();
  const [modules, setModules] = useState<AIModule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<AIModule[]>('/api/ai-modules', token)
      .then((res) => {
        if (!cancelled) setModules(res);
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

  return { modules, loading };
}
