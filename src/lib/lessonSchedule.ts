import type { LessonSession } from '../types';

/** AI modullari (#8, #9, #19, #21, #22) uchun to'liq jadval. */
export function isLessonScheduleComplete(session: LessonSession): boolean {
  return !!(session.teacherId && session.cameraId && session.scheduledStartTime);
}

export function formatLessonScheduleTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('uz-UZ', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16).replace('T', ' ');
  }
}
