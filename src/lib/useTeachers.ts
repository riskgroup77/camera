import { useEffect, useState } from 'react';
import { fetchAllPages } from './apiClient';
import { useAuth } from './auth';
import type { StudentStaffRecord } from '../types';

/** Faqat 'xodim' turidagi StudentStaff yozuvlari — ScheduleLessonModal'da
 * o'qituvchi tanlash uchun (app/jobs/teacher_punctuality_ai.py shu
 * teacherId'ga bog'langan kamerani kuzatadi). */
export function useTeachers() {
  const { token } = useAuth();
  const [teachers, setTeachers] = useState<StudentStaffRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    fetchAllPages<StudentStaffRecord>('/api/students-staff', token, { type: 'xodim' })
      .then((items) => {
        if (!cancelled) setTeachers(items);
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

  return { teachers, loading };
}
