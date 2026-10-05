import { useEffect, useState } from 'react';
import { ApiError } from '../lib/apiClient';
import { getGroupCriteria, type GroupCriteria } from '../lib/groupCriteriaApi';
import type { SampleTeacher } from '../lib/criteriaSample';

export interface GroupCriteriaState {
  data: GroupCriteria | null;
  error: string | null;
  loading: boolean;
  /** Namuna rejimi: to'qima ma'lumot va o'qituvchi ko'rsatkichlari. */
  sample?: SampleTeacher | null;
}

/** Tanlangan guruhning kriteriyalar jadvali; `pulse` da (jonli xabar) yangilanadi. */
export function useGroupCriteria(group: string, date: string, pulse: number, enabled: boolean): GroupCriteriaState {
  const [data, setData] = useState<GroupCriteria | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setData(null);
    setError(null);
  }, [group, date]);

  useEffect(() => {
    if (!group || !enabled) return;
    const controller = new AbortController();
    setLoading(true);
    getGroupCriteria(group, date, { signal: controller.signal })
      .then((next) => {
        setData(next);
        setError(null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError && err.status === 403
            ? 'Kriteriyalarni ko‘rish uchun davomat yoki hisobotlarni ko‘rish huquqi kerak'
            : err instanceof ApiError
              ? err.message
              : "Ma'lumotni olib bo'lmadi",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [group, date, pulse, enabled]);

  return { data, error, loading };
}
