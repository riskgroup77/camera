import { useEffect, useState } from 'react';
import { api } from './apiClient';
import { useAuth } from './auth';
import type { StudentGroup } from '../types';

/** Canonical, live student-group list — backs the group-name autocomplete
 * in ScheduleLessonModal.tsx, mirrors useBuildings.ts/useFaculties.ts. */
export function useGroups() {
  const { token } = useAuth();
  const [groups, setGroups] = useState<StudentGroup[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<StudentGroup[]>('/api/student-groups', token)
      .then((res) => {
        if (!cancelled) setGroups(res);
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

  return { groups, loading };
}
