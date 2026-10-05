import { Link } from 'react-router-dom';
import { Brain, Clock3, DoorOpen, Moon, UserRound, Users } from 'lucide-react';
import {
  Avatar,
  Badge,
  ButtonLink,
  Drawer,
  EmptyState,
  ErrorState,
  ProgressBar,
  Skeleton,
  cn,
  focusRing,
  formatNumber,
  type Tone,
} from '../../ui';
import { getLessonAttendance, situationPaths, type Lesson, type LessonAttendanceRow } from '../../lib/situationApi';
import {
  LESSON_ATTENDANCE_META,
  LESSON_STATE_META,
  TEACHER_STATUS_META,
  lessonRate,
  lessonTime,
  scoreTone,
  toClock,
} from '../../lib/studentAttendance';
import { useAsyncData } from './useAsyncData';

export interface PhotoLookup {
  get: (id: string) => { photoUrl: string | null } | undefined;
}

/** O'qituvchi darsga o'z vaqtida keldimi — yorliq + kelgan vaqti. */
export function TeacherPunctuality({ lesson, size = 'sm' }: { lesson: Lesson; size?: 'sm' | 'md' }) {
  const meta = TEACHER_STATUS_META[lesson.teacherStatus] ?? TEACHER_STATUS_META.nomalum;
  return (
    <Badge tone={meta.tone} dot size={size}>
      {meta.label}
      {lesson.teacherArrivedAt && <span className="ml-1 tabular-nums opacity-80">{lesson.teacherArrivedAt}</span>}
    </Badge>
  );
}

function ScoreChip({ icon: Icon, label, value }: { icon: typeof Brain; label: string; value: number | null }) {
  if (value === null) return null;
  const tone = scoreTone(value);
  return (
    <Badge tone={tone} icon={Icon} title={label}>
      <span className="tabular-nums">{Math.round(value)}</span>
      <span className="sr-only"> — {label}</span>
    </Badge>
  );
}

function stateTone(lesson: Lesson): Tone {
  return LESSON_STATE_META[lesson.state].tone;
}

/** Bir kunlik darslar ro'yxati (guruh sahifasi, "Bugungi darslar"). */
export function LessonList({ lessons, onOpen }: { lessons: readonly Lesson[]; onOpen: (lesson: Lesson) => void }) {
  return (
    <ol className="flex flex-col gap-3">
      {lessons.map((lesson) => {
        const rate = lessonRate(lesson);
        const counted = lesson.finalized ? lesson.present : lesson.seen;
        return (
          <li key={lesson.id}>
            <button
              type="button"
              onClick={() => onOpen(lesson)}
              className={cn(
                'grid w-full gap-x-5 gap-y-3 rounded-card border border-border bg-surface p-4 text-left shadow-card transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-pop sm:grid-cols-[7.5rem_minmax(0,1fr)_14rem] sm:items-center',
                lesson.state === 'ongoing' && 'border-primary/40 ring-1 ring-primary/20',
                focusRing,
              )}
            >
              <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1.5">
                <span className="text-[15px] font-semibold tabular-nums text-fg">{lessonTime(lesson)}</span>
                <Badge tone={stateTone(lesson)} dot={lesson.state === 'ongoing'}>
                  {LESSON_STATE_META[lesson.state].label}
                </Badge>
              </div>

              <div className="min-w-0">
                <p className="truncate text-[15px] font-semibold text-fg">{lesson.subject}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-muted">
                  <span className="inline-flex min-w-0 items-center gap-2">
                    <Avatar name={lesson.teacher || "O'qituvchi"} src={lesson.teacherPhotoUrl} size="xs" />
                    <span className="truncate text-fg">{lesson.teacher || "O'qituvchi ko'rsatilmagan"}</span>
                  </span>
                  <TeacherPunctuality lesson={lesson} />
                  {lesson.room && (
                    <span className="inline-flex items-center gap-1">
                      <DoorOpen size={14} aria-hidden="true" />
                      {lesson.room}
                      {lesson.building ? `, ${lesson.building}` : ''}
                    </span>
                  )}
                </div>
              </div>

              <div className="min-w-0">
                <div className="mb-1.5 flex items-baseline justify-between gap-2 text-[13px]">
                  <span className="text-muted">{lesson.finalized ? 'Qatnashdi' : lesson.state === 'upcoming' ? 'Kutilmoqda' : "Ko'rindi"}</span>
                  <span className="font-semibold tabular-nums text-fg">
                    {formatNumber(counted)}
                    <span className="font-normal text-muted"> / {formatNumber(lesson.expected)}</span>
                  </span>
                </div>
                <ProgressBar value={rate} size="xs" tone={lesson.finalized ? 'auto' : 'primary'} />
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {lesson.late > 0 && <Badge tone="warning">{lesson.late} kech</Badge>}
                  {lesson.absent !== null && lesson.absent > 0 && <Badge tone="danger">{lesson.absent} yo'q</Badge>}
                  <ScoreChip icon={Brain} label="Diqqat" value={lesson.attentionScore} />
                  {lesson.sleepIncidents > 0 && (
                    <Badge tone="warning" icon={Moon} title="Uxlash holatlari">
                      {lesson.sleepIncidents}
                    </Badge>
                  )}
                </div>
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

const ROW_ORDER: Record<string, number> = { kelmadi: 0, kech_keldi: 1, keldi: 2 };

function AttendanceRow({ row, photoUrl, to }: { row: LessonAttendanceRow; photoUrl: string | null; to: string }) {
  const meta = row.status ? LESSON_ATTENDANCE_META[row.status] : null;
  const seenAt = toClock(row.firstSeenAt);
  return (
    <li>
      <Link to={to} className={cn('flex items-center gap-3 rounded-control px-2 py-2 hover:bg-surface-2', focusRing)}>
        <Avatar name={row.fullName} src={photoUrl} size="md" status={meta?.tone ?? null} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{row.fullName}</span>
          <span className="block text-xs text-muted">
            {seenAt ? `Birinchi ko'rindi ${seenAt}` : "Xonada ko'rinmadi"}
            {row.sightings > 0 && ` · ${row.sightings} marta`}
          </span>
        </span>
        {meta ? (
          <Badge tone={meta.tone} dot>
            {meta.label}
          </Badge>
        ) : (
          <Badge tone="neutral">Hisoblanmoqda</Badge>
        )}
      </Link>
    </li>
  );
}

/** Dars tafsiloti: o'qituvchi, xona, ko'rsatkichlar va har bir talabaning
 *  darsdagi davomati (GET /api/lesson-sessions/{id}/attendance). Suratlar
 *  guruh ro'yxatidan id bo'yicha olinadi. */
export function LessonDrawer({
  lesson,
  photos,
  withDate,
  showGroupLink = false,
  onClose,
}: {
  lesson: Lesson | null;
  photos?: PhotoLookup;
  withDate: (path: string) => string;
  showGroupLink?: boolean;
  onClose: () => void;
}) {
  const id = lesson?.id ?? null;
  const attendance = useAsyncData(id, (signal) => getLessonAttendance(id as string, { signal }), { identity: id ?? '' });
  if (!lesson) return null;

  const rows = [...(attendance.data?.rows ?? [])].sort(
    (a, b) => (ROW_ORDER[a.status ?? ''] ?? 3) - (ROW_ORDER[b.status ?? ''] ?? 3) || a.fullName.localeCompare(b.fullName, 'uz'),
  );
  const rate = lessonRate(lesson);

  return (
    <Drawer
      open
      onClose={onClose}
      size="lg"
      title={lesson.subject}
      subtitle={`${lesson.groupName} · ${lessonTime(lesson)}${lesson.room ? ` · ${lesson.room}` : ''}`}
      footer={
        showGroupLink ? (
          <ButtonLink to={withDate(situationPaths.group(lesson.groupName))} size="sm" icon={Users}>
            {lesson.groupName} guruhi
          </ButtonLink>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={stateTone(lesson)} dot={lesson.state === 'ongoing'} size="md">
            {LESSON_STATE_META[lesson.state].label}
          </Badge>
          {lesson.building && <Badge size="md">{lesson.building}</Badge>}
        </div>

        <section className="flex items-center gap-3 rounded-card border border-border p-3">
          <Avatar name={lesson.teacher || "O'qituvchi"} src={lesson.teacherPhotoUrl} size="lg" />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted">O'qituvchi</p>
            {lesson.teacherId ? (
              <Link to={withDate(situationPaths.person(lesson.teacherId))} className={cn('block truncate font-semibold text-fg hover:text-primary', focusRing)}>
                {lesson.teacher}
              </Link>
            ) : (
              <p className="truncate font-semibold text-fg">{lesson.teacher || "Ko'rsatilmagan"}</p>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <TeacherPunctuality lesson={lesson} />
              {lesson.activityScore !== null && (
                <Badge tone={scoreTone(lesson.activityScore)} icon={UserRound}>
                  Faollik {Math.round(lesson.activityScore)}
                </Badge>
              )}
            </div>
          </div>
        </section>

        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: lesson.finalized ? 'Qatnashdi' : "Ko'rindi", value: `${lesson.finalized ? lesson.present : lesson.seen} / ${lesson.expected}`, tone: 'success' as Tone },
            { label: 'Kech kirdi', value: String(lesson.late), tone: 'warning' as Tone },
            { label: 'Qatnashmadi', value: lesson.absent === null ? '—' : String(lesson.absent), tone: 'danger' as Tone },
            { label: 'Diqqat', value: lesson.attentionScore === null ? '—' : `${Math.round(lesson.attentionScore)}`, tone: scoreTone(lesson.attentionScore) },
          ].map((item) => (
            <div key={item.label} className="rounded-control border border-border bg-surface-2/60 px-3 py-2">
              <dt className="text-[11px] font-medium text-muted">{item.label}</dt>
              <dd className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{item.value}</dd>
            </div>
          ))}
        </dl>
        {rate !== null && <ProgressBar value={rate} size="sm" showValue label="Darsdagi davomat" tone={lesson.finalized ? 'auto' : 'primary'} />}
        {lesson.sleepIncidents > 0 && (
          <p className="flex items-center gap-2 text-[13px] text-warning">
            <Moon size={14} aria-hidden="true" />
            {lesson.sleepIncidents} ta uxlash holati qayd etilgan
          </p>
        )}

        <section>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
            <Clock3 size={15} className="text-muted" aria-hidden="true" />
            Talabalar davomati
          </h3>
          {attendance.loading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : attendance.error && !attendance.data ? (
            <ErrorState message={attendance.error} onRetry={attendance.reload} />
          ) : rows.length === 0 ? (
            <EmptyState
              compact
              icon={Clock3}
              title={lesson.state === 'upcoming' ? 'Dars hali boshlanmagan' : 'Davomat hali hisoblanmagan'}
              description={
                lesson.state === 'finished'
                  ? "Dars tugagan, lekin xona kamerasi hech kimni qayd etmagan yoki kamera biriktirilmagan."
                  : `Dars yakunlangach har bir talabaning holati hisoblanadi. Hozircha ishonchli ko'ringanlar: ${lesson.seen} / ${lesson.expected}.`
              }
            />
          ) : (
            <ul className="-mx-2 flex flex-col">
              {rows.map((row) => (
                <AttendanceRow
                  key={row.studentId}
                  row={row}
                  photoUrl={photos?.get(row.studentId)?.photoUrl ?? null}
                  to={withDate(situationPaths.person(row.studentId))}
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </Drawer>
  );
}
