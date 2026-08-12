import { useEffect, useState } from 'react';
import { api } from './apiClient';
import { useAuth } from './auth';
import type { Building } from '../types';

/** Canonical, live building list from the backend — mirrors useFaculties.ts. */
export function useBuildings() {
  const { token } = useAuth();
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<Building[]>('/api/buildings', token)
      .then((res) => {
        if (!cancelled) setBuildings(res);
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

  return { buildings, loading };
}
