import { useEffect, useState } from 'react';
import { ApiError } from '../lib/apiClient';
import {
  getGroup,
  getLessonAttendance,
  type GroupDetail,
  type Lesson,
  type LessonAttendance,
} from '../lib/situationApi';

/**
 * Tanlangan guruhning jonli holati: talabalar (bugungi holati bilan),
 * hozirgi dars va shu darsda kim ko'ringan. `pulse` o'zgarganda (jonli
 * xabar keldi) va har REFRESH_MS da qayta yuklanadi.
 */

export const REFRESH_MS = 20_000;

export interface GroupLive {
  detail: GroupDetail | null;
  current: Lesson | null;
  next: Lesson | null;
  lessonRows: LessonAttendance | null;
  error: string | null;
  loading: boolean;
}

export function pickLessons(lessons: readonly Lesson[]): { current: Lesson | null; next: Lesson | null } {
  const current = lessons.find((lesson) => lesson.state === 'ongoing') ?? null;
  const next =
    [...lessons]
      .filter((lesson) => lesson.state === 'upcoming')
      .sort((a, b) => (a.startsAt ?? '').localeCompare(b.startsAt ?? ''))[0] ?? null;
  return { current, next };
}

export function useGroupLive(group: string, date: string, isToday: boolean, pulse: number): GroupLive {
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [lessonRows, setLessonRows] = useState<LessonAttendance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setDetail(null);
    setLessonRows(null);
  }, [group, date]);

  useEffect(() => {
    if (!group || !isToday) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [group, isToday]);

  useEffect(() => {
    if (!group) return;
    const controller = new AbortController();
    setLoading(true);
    (async () => {
      try {
        const data = await getGroup(group, date, { signal: controller.signal });
        setDetail(data);
        setError(null);
        const { current } = pickLessons(data.lessons);
        setLessonRows(current ? await getLessonAttendance(current.id, { signal: controller.signal }).catch(() => null) : null);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [group, date, pulse, tick]);

  const { current, next } = pickLessons(detail?.lessons ?? []);
  return { detail, current, next, lessonRows, error, loading };
}
