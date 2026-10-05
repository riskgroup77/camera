import { useEffect, useState, type ReactNode } from 'react';
import { BookOpen, ExternalLink, MapPin } from 'lucide-react';
import {
  Avatar,
  Badge,
  ButtonLink,
  Drawer,
  EmptyState,
  ErrorState,
  KeyValue,
  Section,
  SkeletonText,
  StatusBadge,
  formatUzDate,
} from '../../ui';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { situationPaths } from '../../lib/situationApi';
import { LESSON_RELATION_TONE, getPersonDay, hhmm } from '../../lib/teachersApi';
import { formatMinutes } from '../../lib/uzDate';
import { useViewDate } from '../../lib/viewDate';
import type { PersonDay } from '../../types';

export interface TeacherDayDrawerProps {
  /** Ochiq bo'lsa — odam; `null` — yopiq. */
  person: { id: string; fullName: string; photoUrl?: string | null; subtitle?: ReactNode } | null;
  date: string;
  onClose: () => void;
  /** Kun ma'lumotidan oldin ko'rsatiladigan qo'shimcha blok (masalan davr statistikasi). */
  children?: ReactNode;
}

/** O'qituvchining kuni: davomat holati, jadvaldagi darslariga kirgani
 *  (darsga o'z vaqtida kirish) va kun davomida qaysi bino/xonada bo'lgani. */
export function TeacherDayDrawer({ person, date, onClose, children }: TeacherDayDrawerProps) {
  const { withDate } = useViewDate();
  const [data, setData] = useState<PersonDay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const personId = person?.id;

  useEffect(() => {
    if (!personId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    getPersonDay(personId, date, { signal: controller.signal })
      .then(setData)
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [personId, date, nonce]);

  if (!person) return null;

  return (
    <Drawer
      open
      onClose={onClose}
      size="lg"
      title={person.fullName}
      subtitle={formatUzDate(date, { weekday: true })}
      footer={
        <ButtonLink to={withDate(situationPaths.person(person.id))} variant="primary" iconRight={ExternalLink}>
          Profilni ochish
        </ButtonLink>
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex items-center gap-4">
          <Avatar name={person.fullName} src={person.photoUrl} size="xl" shape="square" />
          <div className="min-w-0">
            {person.subtitle && <div className="text-sm text-muted">{person.subtitle}</div>}
            {data && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusBadge status={data.attendanceStatus ?? 'nomalum'} size="md" />
                {data.checkIn && <span className="text-[13px] text-muted">Keldi: <span className="font-medium tabular-nums text-fg">{hhmm(data.checkIn)}</span></span>}
              </div>
            )}
          </div>
        </div>

        {children}

        {loading && <SkeletonText lines={8} />}
        {error && <ErrorState variant="block" message={error} onRetry={() => setNonce((n) => n + 1)} />}

        {data && !loading && (
          <>
            <KeyValue
              items={[
                // Yalang'och "—" sababni aytmasdi: yozuv yo'qmi, xodim
                // kelmaganmi yoki kamera tanimaganmi — farqi bilinmasdi.
                { label: 'Fakultet / bo‘lim', value: [data.faculty, data.unit].filter(Boolean).join(' · ') || 'Reestrda ko‘rsatilmagan' },
                { label: 'Keldi', value: data.checkIn ? <span className="tabular-nums">{hhmm(data.checkIn)}</span> : <span className="text-subtle">Kelishi qayd etilmagan</span> },
                { label: 'Ketdi', value: data.checkOut ? <span className="tabular-nums">{hhmm(data.checkOut)}</span> : <span className="text-subtle">Ketishi qayd etilmagan</span> },
                {
                  label: "Kameralarda ko'rilgan",
                  value: data.firstSeen ? (
                    <span className="tabular-nums">
                      {hhmm(data.firstSeen)} – {hhmm(data.lastSeen)}
                    </span>
                  ) : (
                    <span className="text-subtle">Kameralar tanimagan</span>
                  ),
                },
                { label: 'Binolar', value: data.buildings.join(', ') || <span className="text-subtle">Yo‘q</span> },
              ]}
            />

            <Section title="Jadvaldagi darslari" description={data.lessons.length ? `${data.lessons.length} ta dars` : undefined}>
              {data.lessons.length === 0 ? (
                <EmptyState icon={BookOpen} compact title="Bu kunda jadvalda darsi yo'q" />
              ) : (
                <ul className="divide-y divide-border rounded-card border border-border">
                  {data.lessons.map((lesson) => (
                    <li key={`${lesson.startsAt}-${lesson.groupName}`} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
                      <span className="w-[5.5rem] shrink-0 text-sm font-semibold tabular-nums text-fg">
                        {hhmm(lesson.startsAt)}–{hhmm(lesson.endsAt)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-fg">
                          {lesson.subject} <span className="font-normal text-muted">· {lesson.groupName}</span>
                        </p>
                        <p className="truncate text-xs text-muted">
                          {lesson.camera ?? 'xona kiritilmagan'}
                          {lesson.building ? `, ${lesson.building}` : ''}
                        </p>
                      </div>
                      {lesson.attended ? (
                        <Badge tone={lesson.late ? 'warning' : 'success'} dot>
                          {lesson.late ? 'Kech kirdi' : 'Kirdi'} <span className="ml-1 tabular-nums opacity-80">{hhmm(lesson.arrivedAt)}</span>
                        </Badge>
                      ) : (
                        <Badge tone="danger" dot>
                          Xonada ko&apos;rinmadi
                        </Badge>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Kun davomida qayerda bo'lgan" description={data.visits.length ? `${data.visits.length} ta tashrif` : undefined}>
              {data.visits.length === 0 ? (
                <EmptyState icon={MapPin} compact title="Bu kunda kameralar uni tanimagan" />
              ) : (
                <ol className="relative ml-1.5 flex flex-col gap-2 border-l-2 border-border pl-4">
                  {data.visits.map((visit, index) => {
                    const from = visit.firstSeen.slice(0, 5);
                    const to = visit.lastSeen.slice(0, 5);
                    return (
                      <li key={`${visit.firstSeen}-${index}`} className="relative rounded-control border border-border bg-surface px-3 py-2">
                        <span className="absolute -left-[23px] top-3.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-primary" aria-hidden="true" />
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-sm">
                            <span className="font-semibold tabular-nums text-fg">
                              {from}
                              {to !== from && `–${to}`}
                            </span>{' '}
                            <span className="text-muted">({formatMinutes(visit.durationMinutes)})</span>
                          </span>
                          <Badge tone={LESSON_RELATION_TONE[visit.lesson.relation] ?? 'neutral'}>{visit.lesson.label}</Badge>
                        </div>
                        <p className="mt-0.5 text-xs text-muted">
                          {[visit.building, `${visit.camera}${visit.zone ? ` (${visit.zone})` : ''}`, visit.cameraRole].filter(Boolean).join(' · ')}
                        </p>
                      </li>
                    );
                  })}
                </ol>
              )}
            </Section>
          </>
        )}
      </div>
    </Drawer>
  );
}
