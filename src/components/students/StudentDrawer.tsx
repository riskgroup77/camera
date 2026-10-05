import { useEffect, useCallback } from 'react';
import { ArrowRight, ChevronLeft, ChevronRight, LogIn, LogOut, ScanFace } from 'lucide-react';
import {
  Badge,
  Button,
  ButtonLink,
  Drawer,
  ErrorState,
  Skeleton,
  StatusBadge,
  cn,
  formatPercent,
  formatUzDate,
} from '../../ui';
import { getPerson, situationPaths, type GroupStudent } from '../../lib/situationApi';
import { LESSON_ATTENDANCE_META, biometricsMeta, lessonTime, recentRange, statusMeta } from '../../lib/studentAttendance';
import { DayStrip } from '../attendance/DayStrip';
import { PersonPhoto } from './PersonPhoto';
import { useAsyncData } from './useAsyncData';

const RECENT_DAYS = 14;

function Metric({ icon: Icon, label, value, empty }: { icon: typeof LogIn; label: string; value: string | null; empty: string }) {
  return (
    <div className="rounded-control border border-border bg-surface-2/60 px-3 py-2">
      <p className="flex items-center gap-1 text-[11px] font-medium text-muted">
        <Icon size={12} aria-hidden="true" />
        {label}
      </p>
      {/* Qiymat yo'q bo'lsa izohsiz "—" o'rniga sababi yoziladi. */}
      {value ? (
        <p className="mt-0.5 text-base font-semibold tabular-nums text-fg">{value}</p>
      ) : (
        <p className="mt-0.5 text-[13px] font-medium text-muted">{empty}</p>
      )}
    </div>
  );
}

/** Guruh setkasidan talaba bosilganda: qisqa ma'lumot, so'nggi 14 kun,
 *  shu kungi darslardagi holati va to'liq profilga havola. ← → — qo'shni talaba. */
export function StudentDrawer({
  student,
  groupName,
  date,
  withDate,
  onClose,
  onPrev,
  onNext,
}: {
  student: GroupStudent | null;
  groupName: string;
  date: string;
  withDate: (path: string) => string;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
}) {
  const id = student?.id ?? null;
  const range = recentRange(date, RECENT_DAYS);
  const profile = useAsyncData(id ? `${id}:${date}` : null, (signal) => getPerson(id as string, range, { signal }), {
    identity: id ?? '',
  });

  const onKey = useCallback(
    (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
      if (event.key === 'ArrowLeft' && onPrev) {
        event.preventDefault();
        onPrev();
      } else if (event.key === 'ArrowRight' && onNext) {
        event.preventDefault();
        onNext();
      }
    },
    [onPrev, onNext],
  );
  useEffect(() => {
    if (!student) return;
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [student, onKey]);

  if (!student) return null;
  const meta = statusMeta(student.status);
  const bio = biometricsMeta(student.biometricsStatus);
  const data = profile.data;
  const dayLessons = data?.lessons.filter((lesson) => lesson.date === date).sort((a, b) => (a.startsAt ?? '').localeCompare(b.startsAt ?? '')) ?? [];

  return (
    <Drawer
      open
      onClose={onClose}
      title={student.fullName}
      subtitle={`${groupName} · ${formatUzDate(date, { weekday: true })}`}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div className="flex gap-1.5">
            <Button size="sm" variant="ghost" icon={ChevronLeft} onClick={onPrev} disabled={!onPrev} aria-label="Oldingi talaba">
              <span className="hidden sm:inline">Oldingi</span>
            </Button>
            <Button size="sm" variant="ghost" iconRight={ChevronRight} onClick={onNext} disabled={!onNext} aria-label="Keyingi talaba">
              <span className="hidden sm:inline">Keyingi</span>
            </Button>
          </div>
          <ButtonLink to={withDate(situationPaths.person(student.id))} variant="primary" size="sm" iconRight={ArrowRight}>
            To'liq profil
          </ButtonLink>
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-4">
          <PersonPhoto name={student.fullName} src={student.photoUrl} tone={meta.tone} className="h-32 w-[6.5rem]" />
          <div className="flex min-w-0 flex-col gap-2 pt-1">
            <StatusBadge status={student.status === 'malumot_yoq' ? 'nomalum' : student.status} size="md" time={student.checkIn} />
            <Badge tone={bio.tone} icon={ScanFace}>
              {bio.label}
            </Badge>
            {student.biometricsStatus !== 'tasdiqlangan' && (
              <p className="text-xs leading-relaxed text-muted">
                Kameralar bu talabani taniy olmaydi — davomat avtomatik yozilmaydi.
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Metric icon={LogIn} label="Keldi" value={student.checkIn} empty="Qayd etilmagan" />
          <Metric icon={LogOut} label="Ketdi" value={student.checkOut} empty="Chiqishi qayd etilmagan" />
        </div>

        <section>
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-fg">So'nggi {RECENT_DAYS} kun</h3>
            {data && (
              <p className="text-xs text-muted">
                Davomat <span className="font-semibold tabular-nums text-fg">{formatPercent(data.totals.rate)}</span>
                {data.totals.avgArrival && (
                  <>
                    {' '}
                    · o'rtacha <span className="font-semibold tabular-nums text-fg">{data.totals.avgArrival}</span>
                  </>
                )}
              </p>
            )}
          </div>
          {profile.loading ? (
            <Skeleton className="h-9 w-full" />
          ) : profile.error && !data ? (
            <ErrorState message={profile.error} onRetry={profile.reload} />
          ) : data ? (
            <>
              <DayStrip days={data.calendar} />
              <p className="mt-2 text-xs text-muted">
                {/* totals.present kech kelganlarni ham o'z ichiga oladi — uch son
                    qo'shilganda jami kunni bersin uchun ayirib ko'rsatiladi. */}
                {Math.max(0, data.totals.present - data.totals.late)} kun o'z vaqtida · {data.totals.late} kech · {data.totals.absent} kelmadi
              </p>
            </>
          ) : null}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-fg">Shu kungi darslarda</h3>
          {profile.loading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : profile.error && !data ? (
            // Ilgari so'rov yiqilganda ham "dars jadvalda yo'q" deb yozilardi —
            // bu yolg'on bo'sh holat edi.
            <ErrorState message={profile.error} onRetry={profile.reload} />
          ) : dayLessons.length === 0 ? (
            <p className="rounded-control bg-surface-2 px-3 py-2.5 text-[13px] text-muted">Bu kunda dars jadvalda yo'q.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border rounded-control border border-border">
              {dayLessons.map((lesson) => {
                const own = lesson.attendanceStatus ? LESSON_ATTENDANCE_META[lesson.attendanceStatus] : null;
                return (
                  <li key={lesson.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-fg">{lesson.subject}</p>
                      <p className="truncate text-xs text-muted">
                        <span className="tabular-nums">{lessonTime(lesson)}</span>
                        {lesson.room ? ` · ${lesson.room}` : ''}
                      </p>
                    </div>
                    {own ? (
                      <Badge tone={own.tone} dot>
                        {own.label}
                        {lesson.firstSeen && <span className="ml-1 tabular-nums opacity-80">{lesson.firstSeen}</span>}
                      </Badge>
                    ) : (
                      <Badge tone="neutral" className={cn(lesson.state === 'upcoming' && 'opacity-70')}>
                        {lesson.state === 'upcoming' ? 'Boshlanmagan' : 'Hisoblanmoqda'}
                      </Badge>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </Drawer>
  );
}
