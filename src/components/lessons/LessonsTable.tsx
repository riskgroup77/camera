import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Avatar, DataTable, cn, focusRing, type DataTableColumn } from '../../ui';
import { situationPaths, type Lesson } from '../../lib/situationApi';
import { useViewDate } from '../../lib/viewDate';
import { TEACHER_STATUS_META } from '../../lib/teachersApi';
import { LessonAttendanceBar, LessonStateBadge, ScoreValue, TeacherPunctualityBadge } from './LessonBits';

const STATUS_ORDER = { kelmadi: 0, kechikdi: 1, kutilmoqda: 2, nomalum: 3, oz_vaqtida: 4 } as const;

function InlineLink({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  return (
    <Link
      to={to}
      onClick={(event) => event.stopPropagation()}
      className={cn('rounded font-medium text-fg hover:text-primary hover:underline', focusRing, className)}
    >
      {children}
    </Link>
  );
}

export interface LessonsTableProps {
  rows: readonly Lesson[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onRowClick?: (lesson: Lesson) => void;
  selectedId?: string | null;
  /** Holat ustuni (Barchasi tabida foydali). */
  showState?: boolean;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  footer?: ReactNode;
}

/** Darslar jadvali — /darslar va kafedra sahifasidagi "Darslar" tabi uchun. */
export function LessonsTable({ rows, loading, error, onRetry, onRowClick, selectedId, showState, emptyTitle, emptyDescription, footer }: LessonsTableProps) {
  const { withDate } = useViewDate();

  const columns: DataTableColumn<Lesson>[] = [
    {
      key: 'time',
      header: 'Vaqt',
      width: '7rem',
      sortValue: (l) => l.startsAt ?? '99:99',
      cell: (l) => (
        <div className="flex flex-col gap-1">
          <span className="font-semibold tabular-nums text-fg">
            {l.startsAt ?? '—'}
            {l.endsAt && <span className="font-normal text-muted">–{l.endsAt}</span>}
          </span>
          {showState && <LessonStateBadge state={l.state} />}
        </div>
      ),
    },
    {
      key: 'group',
      header: 'Guruh',
      sortValue: (l) => l.groupName,
      cell: (l) => (
        <div className="min-w-0">
          <InlineLink to={withDate(situationPaths.group(l.groupName))}>{l.groupName}</InlineLink>
          <p className="truncate text-xs text-muted">{l.faculty}</p>
        </div>
      ),
    },
    {
      key: 'subject',
      header: 'Fan',
      sortValue: (l) => l.subject,
      cell: (l) => <span className="line-clamp-2">{l.subject}</span>,
    },
    {
      key: 'teacher',
      header: "O'qituvchi",
      sortValue: (l) => STATUS_ORDER[l.teacherStatus] ?? 9,
      mobileLabel: "O'qituvchi",
      cell: (l) => (
        <div className="flex min-w-0 items-center gap-2.5">
          <Avatar name={l.teacher} src={l.teacherPhotoUrl} size="sm" status={TEACHER_STATUS_META[l.teacherStatus]?.tone === 'neutral' ? null : TEACHER_STATUS_META[l.teacherStatus]?.tone} className="hidden md:inline-flex" />
          <div className="min-w-0">
            {l.teacherId ? (
              <InlineLink to={withDate(situationPaths.person(l.teacherId))} className="block truncate">
                {l.teacher}
              </InlineLink>
            ) : (
              <span className="block truncate font-medium">{l.teacher}</span>
            )}
            <TeacherPunctualityBadge status={l.teacherStatus} time={l.teacherArrivedAt} className="mt-1" />
          </div>
        </div>
      ),
    },
    {
      key: 'room',
      header: 'Xona / bino',
      hideOnMobile: false,
      sortValue: (l) => l.room ?? '',
      cell: (l) =>
        l.room ? (
          <div className="min-w-0">
            <p className="truncate">{l.room}</p>
            {l.building && <p className="truncate text-xs text-muted">{l.building}</p>}
          </div>
        ) : (
          <span className="text-[13px] text-warning" title="Xona kamerasi biriktirilmagan — AI kuzata olmaydi">
            Kamera yo'q
          </span>
        ),
    },
    {
      key: 'attendance',
      header: 'Davomat',
      width: '10rem',
      sortValue: (l) => (l.expected ? l.present / l.expected : null),
      sortFirst: 'asc',
      cell: (l) => <LessonAttendanceBar lesson={l} />,
    },
    {
      key: 'scores',
      header: 'Diqqat / faollik',
      align: 'right',
      mobileLabel: 'Diqqat / faollik',
      sortValue: (l) => l.attentionScore,
      cell: (l) => (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <ScoreValue value={l.attentionScore} label="Talabalar diqqati" />
          <span className="text-subtle">/</span>
          <ScoreValue value={l.activityScore} label="O'qituvchi faolligi" />
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(l) => l.id}
      onRowClick={onRowClick}
      selectedKey={selectedId}
      rowTone={(l) => (l.teacherStatus === 'kelmadi' ? 'danger' : l.teacherStatus === 'kechikdi' ? 'warning' : l.state === 'ongoing' ? 'primary' : null)}
      loading={loading}
      error={error}
      onRetry={onRetry}
      emptyTitle={emptyTitle ?? 'Darslar topilmadi'}
      emptyDescription={emptyDescription}
      ariaLabel="Darslar"
      mobileTitleKey="subject"
      footer={footer}
    />
  );
}
