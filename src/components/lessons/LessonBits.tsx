import { Badge, ProgressBar, cn } from '../../ui';
import type { Lesson, LessonState, TeacherStatus } from '../../lib/situationApi';
import { LESSON_STATE_META, TEACHER_STATUS_META } from '../../lib/studentAttendance';
import type { Tone } from '../../ui';

const STATE_TONE: Record<LessonState, Tone> = { ongoing: 'primary', upcoming: 'neutral', finished: 'neutral' };

/** O'qituvchining darsga kelishi (punktuallik) yorlig'i. */
export function TeacherPunctualityBadge({ status, time, className }: { status: TeacherStatus; time?: string | null; className?: string }) {
  const meta = TEACHER_STATUS_META[status] ?? TEACHER_STATUS_META.nomalum;
  return (
    <Badge tone={meta.tone} dot className={className} title="O'qituvchi darsga kelishi">
      {meta.label}
      {time && <span className="ml-1 tabular-nums opacity-80">{time}</span>}
    </Badge>
  );
}

export function LessonStateBadge({ state }: { state: LessonState }) {
  return (
    <Badge tone={STATE_TONE[state]} dot={state === 'ongoing'}>
      {LESSON_STATE_META[state].label}
    </Badge>
  );
}

/** Talabalar davomati: keldi / kech / kelmadi chizig'i va raqamlar.
 *  Yakunlanmagan darsda "kelmadi" noma'lum — o'rniga "kutilmoqda". */
export function LessonAttendanceBar({ lesson, className }: { lesson: Pick<Lesson, 'expected' | 'present' | 'late' | 'absent' | 'finalized' | 'state'>; className?: string }) {
  const onTime = Math.max(0, lesson.present - lesson.late);
  const absent = lesson.absent ?? 0;
  const pending = lesson.absent === null ? Math.max(0, lesson.expected - lesson.present) : 0;
  if (lesson.expected === 0 && lesson.present === 0) return <span className="text-[13px] text-subtle">—</span>;
  return (
    <div className={cn('min-w-[8rem]', className)}>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold tabular-nums text-fg">
          {lesson.present}/{lesson.expected}
        </span>
        <span className="tabular-nums text-muted">
          {lesson.late > 0 && <span className="text-warning">{lesson.late} kech</span>}
          {lesson.late > 0 && lesson.absent ? ' · ' : ''}
          {lesson.absent ? <span className="text-danger">{lesson.absent} yo'q</span> : null}
          {lesson.absent === null && lesson.state === 'upcoming' && 'boshlanmagan'}
        </span>
      </div>
      <ProgressBar
        size="xs"
        segments={[
          { value: onTime, tone: 'success', label: 'Keldi' },
          { value: lesson.late, tone: 'warning', label: 'Kech keldi' },
          { value: absent, tone: 'danger', label: 'Kelmadi' },
          { value: pending, tone: 'neutral', label: "Hali noma'lum" },
        ]}
      />
    </div>
  );
}

/** Diqqat/faollik bali: o'lchanmagan → "—" (0% emas). */
export function ScoreValue({ value, label }: { value: number | null; label?: string }) {
  if (value === null) return <span className="text-subtle" title="O'lchanmagan">—</span>;
  const tone = value >= 75 ? 'text-success' : value >= 55 ? 'text-warning' : 'text-danger';
  return (
    <span className="tabular-nums" title={label}>
      <span className={cn('font-semibold', tone)}>{Math.round(value)}</span>
      <span className="text-muted">%</span>
    </span>
  );
}
