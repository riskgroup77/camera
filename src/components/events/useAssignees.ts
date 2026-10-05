import { useEffect, useState } from 'react';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { EventAssignee } from '../../types';

// Ro'yxat kam o'zgaradi — sahifa umrida bitta so'rov (token bo'yicha).
let cache: { token: string; promise: Promise<EventAssignee[]> } | null = null;

/** Tayinlash ro'yxati: hodisalarni ko'rib chiqish huquqi bor foydalanuvchilar. */
export function useAssignees(enabled = true): { assignees: EventAssignee[]; error: boolean } {
  const { token } = useAuth();
  const [assignees, setAssignees] = useState<EventAssignee[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!enabled || !token) return;
    if (!cache || cache.token !== token) {
      const promise = api.get<EventAssignee[]>('/api/events/assignees', token);
      cache = { token, promise };
      // Xato keshda qolmasin — keyingi ochilishda qayta so'raladi.
      promise.catch(() => {
        if (cache?.promise === promise) cache = null;
      });
    }
    let cancelled = false;
    cache.promise
      .then((list) => {
        if (!cancelled) {
          setAssignees(list);
          setError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, token]);

  return { assignees, error };
}
