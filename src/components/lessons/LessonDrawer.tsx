import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, Trash2, Users } from 'lucide-react';
import {
  Avatar,
  Button,
  ButtonLink,
  Drawer,
  EmptyState,
  ErrorState,
  KeyValue,
  ProgressBar,
  Section,
  SkeletonText,
  StatusBadge,
  Tabs,
  formatUzDate,
} from '../../ui';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { getLessonAttendance, situationPaths, type Lesson, type LessonAttendance } from '../../lib/situationApi';
import { isLessonTracked } from '../../lib/teachersApi';
import { useViewDate } from '../../lib/viewDate';
import { LessonStateBadge, ScoreValue, TeacherPunctualityBadge } from './LessonBits';

type Filter = 'all' | 'keldi' | 'kech_keldi' | 'kelmadi';

function firstSeenTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(11, 16) || null;
  return date.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Tashkent' });
}

export interface LessonDrawerProps {
  lesson: Lesson | null;
  onClose: () => void;
  /** Jadvalni tahrirlash (manageLessons). */
  onEditSchedule?: (lesson: Lesson) => void;
  /** Monitoring yozuvini o'chirish (manageLessons). */
  onDelete?: (lesson: Lesson) => void;
}

/** Dars tafsiloti: vaqt, xona, o'qituvchi punktualligi, AI ballari va
 *  talabalarning shu darsdagi davomati. */
export function LessonDrawer({ lesson, onClose, onEditSchedule, onDelete }: LessonDrawerProps) {
  const { withDate } = useViewDate();
  const [data, setData] = useState<LessonAttendance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [filter, setFilter] = useState<Filter>('all');

  const lessonId = lesson?.id;
  useEffect(() => {
    if (!lessonId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    getLessonAttendance(lessonId, { signal: controller.signal })
      .then(setData)
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Davomatni yuklab bo'lmadi");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [lessonId, nonce]);

  useEffect(() => setFilter('all'), [lessonId]);

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    return filter === 'all' ? all : all.filter((r) => r.status === filter);
  }, [data, filter]);

  if (!lesson) return null;

  const tracked = isLessonTracked(lesson);
  // Bu endpointda `present` — faqat o'z vaqtida kelganlar (kech kelganlar `late`da).
  const counts = data ? { keldi: data.present, kech: data.late, kelmadi: data.absent } : null;

  return (
    <Drawer
      open={lesson !== null}
      onClose={onClose}
      size="lg"
      title={lesson.subject}
      subtitle={`${lesson.groupName} · ${formatUzDate(lesson.date, { weekday: true })}${lesson.startsAt ? ` · ${lesson.startsAt}${lesson.endsAt ? `–${lesson.endsAt}` : ''}` : ''}`}
      footer={
        onEditSchedule || onDelete ? (
          <>
            {onDelete && (
              <Button variant="ghost" icon={Trash2} onClick={() => onDelete(lesson)} className="mr-auto text-danger">
                O'chirish
              </Button>
            )}
            {onEditSchedule && (
              <Button icon={CalendarClock} onClick={() => onEditSchedule(lesson)}>
                Jadvalni tahrirlash
              </Button>
            )}
          </>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center gap-2">
          <LessonStateBadge state={lesson.state} />
          {!tracked && (
            <span className="text-xs text-warning">Jadval to'liq emas — AI bu darsni to'liq kuzata olmaydi</span>
          )}
        </div>

        <div className="flex items-center gap-3 rounded-card border border-border bg-surface-2 p-3">
          <Avatar name={lesson.teacher} src={lesson.teacherPhotoUrl} size="lg" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-fg">{lesson.teacher}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <TeacherPunctualityBadge status={lesson.teacherStatus} />
              {lesson.teacherArrivedAt && <span className="text-xs text-muted">Xonaga kirdi: {lesson.teacherArrivedAt}</span>}
            </div>
          </div>
          {lesson.teacherId && (
            <ButtonLink to={withDate(situationPaths.person(lesson.teacherId))} size="sm" variant="ghost">
              Profil
            </ButtonLink>
          )}
        </div>

        <KeyValue
          items={[
            { label: 'Guruh', value: <ButtonLink to={withDate(situationPaths.group(lesson.groupName))} variant="ghost" size="sm" className="-my-1 -mr-2">{lesson.groupName}</ButtonLink> },
            { label: 'Fakultet', value: lesson.faculty || '—' },
            { label: 'Xona (kamera)', value: lesson.room ?? "Biriktirilmagan" },
            { label: 'Bino', value: lesson.building ?? '—' },
            { label: 'Talabalar diqqati', value: <ScoreValue value={lesson.attentionScore} /> },
            { label: "O'qituvchi faolligi", value: <ScoreValue value={lesson.activityScore} /> },
            { label: 'Uxlash holatlari', value: lesson.sleepIncidents },
            { label: 'AI tekshiruvi (vaqtida)', value: lesson.teacherOnTime === null ? 'Tekshirilmagan' : lesson.teacherOnTime ? 'Ha' : "Yo'q" },
          ]}
        />

        <Section
          title="Talabalar davomati"
          description={
            data
              ? data.finalized
                ? `${data.present + data.late} keldi (${data.late} kech), ${data.absent} kelmadi — kutilgan ${lesson.expected}`
                : `Dars yakunlanmagan: hozircha ${lesson.seen} ta talaba ishonchli ko'rindi (kutilgan ${lesson.expected})`
              : undefined
          }
        >
          {loading && <SkeletonText lines={6} />}
          {error && <ErrorState variant="block" message={error} onRetry={() => setNonce((n) => n + 1)} />}
          {data && !loading && (
            <div className="flex flex-col gap-3">
              {counts && data.finalized && (
                <ProgressBar
                  size="sm"
                  segments={[
                    { value: counts.keldi, tone: 'success', label: 'Keldi' },
                    { value: counts.kech, tone: 'warning', label: 'Kech keldi' },
                    { value: counts.kelmadi, tone: 'danger', label: 'Kelmadi' },
                  ]}
                />
              )}
              {data.rows.length === 0 ? (
                <EmptyState
                  icon={Users}
                  compact
                  title={data.finalized ? "Hech kim ko'rinmadi" : "Hali ma'lumot yo'q"}
                  description={
                    data.finalized
                      ? "Dars tugagan, lekin xona kamerasi talabalarni tanimadi."
                      : "Davomat dars tugagach avtomatik hisoblanadi (xona kamerasi bo'yicha)."
                  }
                />
              ) : (
                <>
                  <Tabs
                    variant="segmented"
                    size="sm"
                    value={filter}
                    onChange={setFilter}
                    ariaLabel="Davomat filtri"
                    tabs={[
                      { id: 'all', label: 'Barchasi', count: data.rows.length },
                      { id: 'keldi', label: 'Keldi', count: data.present },
                      { id: 'kech_keldi', label: 'Kech', count: data.late },
                      { id: 'kelmadi', label: 'Kelmadi', count: data.absent },
                    ]}
                  />
                  <ul className="divide-y divide-border rounded-card border border-border">
                    {rows.map((row) => (
                      <li key={row.studentId} className="flex items-center gap-3 px-3 py-2.5">
                        <Avatar name={row.fullName} size="sm" />
                        <Link
                          to={withDate(situationPaths.person(row.studentId))}
                          className="min-w-0 flex-1 truncate rounded text-sm font-medium text-fg hover:text-primary hover:underline"
                        >
                          {row.fullName}
                        </Link>
                        {firstSeenTime(row.firstSeenAt) && <span className="text-xs tabular-nums text-muted">{firstSeenTime(row.firstSeenAt)}</span>}
                        <StatusBadge status={row.status ?? 'kutilmoqda'} />
                      </li>
                    ))}
                    {rows.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">Bu holatda talaba yo'q</li>}
                  </ul>
                </>
              )}
            </div>
          )}
        </Section>
      </div>
    </Drawer>
  );
}
