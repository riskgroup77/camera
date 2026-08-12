import { useEffect, useState } from 'react';
import { api } from './apiClient';
import { useAuth } from './auth';
import type { Faculty } from '../types';

/**
 * Canonical, live faculty list from the backend — used anywhere a form needs
 * to pick a faculty by name (students/staff, groups). Replaces the old
 * hardcoded STUDENT_STAFF_FACULTIES mock list, which could silently drift
 * out of sync with Org Structure once faculties became editable there.
 */
export function useFaculties() {
  const { token } = useAuth();
  const [faculties, setFaculties] = useState<Faculty[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<Faculty[]>('/api/faculties', token)
      .then((res) => {
        if (!cancelled) setFaculties(res);
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

  return { faculties, loading };
}
