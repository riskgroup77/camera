import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarCheck2, ChevronRight, Gauge, QrCode as QrIcon, ScanFace, SearchX, Target, TrendingUp, Users } from 'lucide-react';
import {
  Button,
  Card,
  DataTable,
  DatePicker,
  EmptyState,
  ErrorState,
  ProgressBar,
  Skeleton,
  FilterBar,
  cn,
  focusRing,
  formatNumber,
  formatPercent,
  formatUzDate,
  type DataTableColumn,
  type FilterFieldEntry,
} from '../../ui';
import { NO_FACULTY_ID, getEnrollment, getEnrollmentGroups, situationPaths, type EnrollCounts, type EnrollGroup, type Enrollment } from '../../lib/situationApi';
import {
  enrollPace,
  enrollTone,
  neededPerDay,
  normalizeText,
  projectCompletion,
  recordSnapshot,
  type EnrollSnapshot,
} from '../../lib/studentAttendance';
import { usePersistedState } from '../../lib/usePersistedState';
import { GroupEnrollDrawer, type EnrollDrawerTarget } from './GroupEnrollDrawer';
import { useAsyncData } from './useAsyncData';

const SNAPSHOT_KEY = 'talabalar.yuz.kuzatuv';
const TARGET_KEY = 'talabalar.yuz.maqsad';
/** Institut bo'yicha davomat ko'rsatila boshlanadigan chegara (server: students.pct >= 5). */
const INSTITUTE_READY_PCT = 5;

/** Fakultet ro'yxatda topilmaganda — nol ko'rsatkich (bo'sh sahifa o'rniga). */
const EMPTY_ENROLL_COUNTS: EnrollCounts = { total: 0, confirmed: 0, pending: 0, none: 0, pct: null };

type Stage = '' | 'none' | 'progress' | 'done';
const STAGES: { value: Stage; label: string }[] = [
  { value: 'none', label: 'Boshlanmagan (0%)' },
  { value: 'progress', label: 'Jarayonda' },
  { value: 'done', label: 'Deyarli tayyor (≥90%)' },
];

function stageOf(g: EnrollGroup): Stage {
  // Talabasi yo'q guruhda yig'iladigan yuz ham yo'q. Ilgari u "Boshlanmagan
  // (0%)" ga tushib, "N boshlanmagan" hisobini sun'iy shishirardi.
  if (g.total === 0) return 'done';
  if (!g.pct) return 'none';
  return g.pct >= 90 ? 'done' : 'progress';
}

interface CampaignData {
  enrollment: Enrollment;
  groups: EnrollGroup[];
}

/**
 * "Yuz topshirish" kampaniyasi: umumiy progress, maqsad sanasi va sur'at,
 * fakultetlar kartalari, eng orqadagi guruhlar jadvali va har guruh uchun
 * "Topshirmaganlar" paneli (QR karta bilan). `facultyId` berilsa — bitta
 * fakultet doirasida (NO_FACULTY_ID — fakultetsizlar).
 */
export function EnrollmentCampaign({ facultyId, today, withDate }: { facultyId?: string; today: string; withDate: (path: string) => string }) {
  const scoped = facultyId !== undefined;
  const apiFaculty = scoped && facultyId !== NO_FACULTY_ID ? facultyId : undefined;
  const res = useAsyncData<CampaignData>(
    `enr|${facultyId ?? '*'}`,
    async (signal) => {
      const [enrollment, groups] = await Promise.all([getEnrollment({ signal }), getEnrollmentGroups(apiFaculty ? { facultyId: apiFaculty } : {}, { signal })]);
      return { enrollment, groups: facultyId === NO_FACULTY_ID ? groups.filter((g) => g.facultyId === null) : groups };
    },
    { identity: facultyId ?? '*', refreshMs: 120_000 },
  );
  const data = res.data;

  const [query, setQuery] = useState('');
  const [faculty, setFaculty] = useState('');
  const [course, setCourse] = useState('');
  const [stage, setStage] = useState<Stage>('');
  const [target, setTarget] = useState<EnrollDrawerTarget | null>(null);

  const counts: EnrollCounts | null = useMemo(() => {
    if (!data) return null;
    if (!scoped) return data.enrollment.students;
    const f = data.enrollment.byFaculty.find((x) => (facultyId === NO_FACULTY_ID ? x.id === null : x.id === facultyId));
    // Fakultet ro'yxatda yo'q (masalan "Fakultetsiz" talaba qolmagan) —
    // sahifa bo'sh qolmasin, nol ko'rsatkich bilan chiziladi.
    return f ?? EMPTY_ENROLL_COUNTS;
  }, [data, scoped, facultyId]);

  const facultyOptions = useMemo(
    () => (data?.enrollment.byFaculty ?? []).filter((f) => f.total > 0).map((f) => ({ value: f.id ?? NO_FACULTY_ID, label: f.name })),
    [data],
  );
  const courseOptions = useMemo(() => {
    const set = new Set<number>();
    for (const g of data?.groups ?? []) if (g.course) set.add(g.course);
    return [...set].sort((a, b) => a - b).map((c) => ({ value: String(c), label: `${c}-kurs` }));
  }, [data]);

  const rows = useMemo(() => {
    const needle = normalizeText(query);
    return (data?.groups ?? []).filter(
      (g) =>
        (!needle || normalizeText(g.name).includes(needle)) &&
        (!faculty || (g.facultyId ?? NO_FACULTY_ID) === faculty) &&
        (!course || String(g.course) === course) &&
        (!stage || stageOf(g) === stage),
    );
  }, [data, query, faculty, course, stage]);
  // Sarlavhadagi uchta son AYNAN jadvaldagi qatorlardan hisoblanadi.
  // Ilgari ular filtrlanmagan to'liq ro'yxatdan olinardi: qidiruv yoki
  // fakultet tanlanganda tepadagi "12 boshlanmagan" jadvaldagi 2 ta
  // qatorga zid chiqardi.
  const stageCounts = useMemo(() => {
    const out = { none: 0, progress: 0, done: 0 };
    for (const g of rows) out[stageOf(g) as 'none' | 'progress' | 'done']++;
    return out;
  }, [rows]);

  const filterFields: FilterFieldEntry[] = [
    { kind: 'search', value: query, onChange: setQuery, placeholder: 'Guruh nomi…' },
    // Fakultet tanlagichi fakultet ichidagi ko'rinishda ortiqcha.
    !scoped && { kind: 'select', value: faculty, onChange: setFaculty, options: facultyOptions, placeholder: 'Barcha fakultetlar', ariaLabel: 'Fakultet' },
    courseOptions.length > 1 && { kind: 'select', value: course, onChange: setCourse, options: courseOptions, placeholder: 'Barcha kurslar', ariaLabel: 'Kurs' },
    { kind: 'select', value: stage, onChange: (v) => setStage(v as Stage), options: STAGES, placeholder: 'Har qanday holat', ariaLabel: 'Holat' },
  ];
  // Ko'rinmayotgan tanlagich ham tozalansin (fakultet/kurs ro'yxati
  // o'zgarganda qiymat qolib ketmasin).
  const reset = () => {
    setQuery('');
    setFaculty('');
    setCourse('');
    setStage('');
  };

  const columns: DataTableColumn<EnrollGroup>[] = [
    {
      key: 'name',
      header: 'Guruh',
      sortValue: (g) => g.name,
      cell: (g) => (
        <div className="min-w-0">
          <p className="whitespace-nowrap font-medium text-fg">{g.name}</p>
          {!scoped && <p className="truncate text-xs text-muted md:hidden">{g.faculty ?? 'Fakultetsiz'}</p>}
        </div>
      ),
    },
    ...(!scoped
      ? [{ key: 'faculty', header: 'Fakultet', cell: (g: EnrollGroup) => g.faculty ?? 'Fakultetsiz', sortValue: (g: EnrollGroup) => g.faculty, hideOnMobile: true }]
      : []),
    { key: 'course', header: 'Kurs', cell: (g) => (g.course ? `${g.course}-kurs` : '—'), sortValue: (g) => g.course, hideOnMobile: true },
    {
      key: 'done',
      header: 'Topshirdi',
      align: 'right',
      mobileLabel: 'Topshirdi',
      sortValue: (g) => g.confirmed,
      cell: (g) => (
        <span className="tabular-nums">
          <span className="font-semibold text-fg">{g.confirmed}</span>
          <span className="text-muted"> / {g.total}</span>
          {g.pending > 0 && <span className="ml-1 text-xs text-info">+{g.pending} kutilmoqda</span>}
        </span>
      ),
    },
    {
      key: 'pct',
      header: 'Progress',
      width: '13rem',
      sortValue: (g) => g.pct,
      sortFirst: 'asc',
      cell: (g) => (
        <div className="flex items-center gap-2">
          <ProgressBar value={g.pct ?? 0} tone={enrollTone(g.pct)} size="xs" className="flex-1" ariaLabel={`${g.name}: ${formatPercent(g.pct)}`} />
          <span className="w-12 text-right font-semibold tabular-nums">{formatPercent(g.pct)}</span>
        </div>
      ),
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      width: '11rem',
      cell: (g) =>
        g.total > g.confirmed ? (
          <Button
            size="sm"
            variant="secondary"
            icon={QrIcon}
            onClick={(e) => {
              e.stopPropagation();
              setTarget({ name: g.name, faculty: g.faculty });
            }}
          >
            {g.total - g.confirmed} topshirmagan
          </Button>
        ) : g.total > 0 ? (
          <span className="text-xs font-medium text-success">Hammasi topshirgan</span>
        ) : null,
    },
  ];

  if (res.loading) {
    return (
      <div className="flex flex-col gap-5">
        <Skeleton className="h-48 rounded-card" />
        {!scoped && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-36 rounded-card" />
            ))}
          </div>
        )}
        <Skeleton className="h-80 rounded-card" />
      </div>
    );
  }
  if (res.error && !data) {
    return (
      <Card padding="none">
        <ErrorState variant="block" message={res.error} onRetry={res.reload} />
      </Card>
    );
  }
  if (!data || !counts) return null;

  const faculties = data.enrollment.byFaculty.filter((f) => f.total > 0);

  return (
    <div className="flex flex-col gap-5">
      {/* Fonda yangilash yiqilsa ham foydalanuvchi eskirgan sonlarni ko'rib
          turardi va buni bilmasdi — xato endi ko'rsatiladi. */}
      {res.error && <ErrorState title="Yangilab bo'lmadi — oxirgi ma'lumot ko'rsatilmoqda" message={res.error} onRetry={res.reload} />}
      <CampaignHero counts={counts} today={today} institute={!scoped} />

      {!scoped && faculties.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-fg">Fakultetlar</h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {faculties.map((f) => (
              <FacultyEnrollCard key={f.id ?? 'none'} faculty={f} to={withDate(`${situationPaths.faculty(f.id)}?korinish=yuz`)} />
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-fg">Guruhlar — eng orqadagilar birinchi</h2>
          <p className="text-[13px] text-muted">
            <span className="font-semibold text-danger">{stageCounts.none}</span> boshlanmagan ·{' '}
            <span className="font-semibold text-warning">{stageCounts.progress}</span> jarayonda ·{' '}
            <span className="font-semibold text-success">{stageCounts.done}</span> tayyor
          </p>
        </div>
        <FilterBar fields={filterFields} onReset={reset} />
        {data.groups.length === 0 ? (
          <EmptyState icon={Users} title="Guruhlar yo'q" description="Talabalar «Reestr» bo'limida guruhlarga biriktiriladi." />
        ) : rows.length === 0 ? (
          <EmptyState compact icon={SearchX} title="Mos guruh topilmadi" action={<Button size="sm" onClick={reset}>Filtrni tozalash</Button>} />
        ) : (
          <DataTable
            ariaLabel="Guruhlar bo'yicha yuz topshirish"
            columns={columns}
            rows={rows}
            rowKey={(g) => g.name}
            onRowClick={(g) => setTarget({ name: g.name, faculty: g.faculty })}
            selectedKey={target?.name ?? null}
            maxHeight="36rem"
          />
        )}
      </section>

      <GroupEnrollDrawer target={target} onClose={() => setTarget(null)} withDate={withDate} />
    </div>
  );
}

function readSnapshots(): EnrollSnapshot[] {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? (parsed as EnrollSnapshot[]) : [];
  } catch {
    return [];
  }
}

/** Katta progress: tasdiqlangan / jami, maqsad sanasi (brauzerda saqlanadi), sur'at va prognoz. */
function CampaignHero({ counts, today, institute }: { counts: EnrollCounts; today: string; institute: boolean }) {
  const [targetDate, setTargetDate] = usePersistedState<string>(TARGET_KEY, '');
  const [snapshots, setSnapshots] = useState<EnrollSnapshot[]>(() => readSnapshots());

  // Institut darajasidagi sonni kuniga bir marta eslab qolamiz — sur'at shundan.
  useEffect(() => {
    if (!institute) return;
    setSnapshots((prev) => {
      const next = recordSnapshot(prev, today, counts.confirmed);
      try {
        localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(next));
      } catch {
        /* saqlab bo'lmasa ham ishlayveradi */
      }
      return next;
    });
  }, [institute, today, counts.confirmed]);

  const remaining = Math.max(0, counts.total - counts.confirmed);
  const pct = counts.pct ?? 0;
  const pace = institute ? enrollPace(snapshots, today) : null;
  const eta = pace ? projectCompletion(remaining, pace.perDay, today) : null;
  const perDay = targetDate ? neededPerDay(remaining, today, targetDate) : null;

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-2 text-sm font-medium text-primary">
            <ScanFace size={16} aria-hidden="true" />
            Yuz topshirish kampaniyasi
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-1">
            <p className="text-5xl font-semibold leading-none tracking-tight tabular-nums text-fg">{formatPercent(counts.pct, 1)}</p>
            <p className="pb-1 text-sm text-muted">
              <span className="font-semibold tabular-nums text-fg">{formatNumber(counts.confirmed)}</span> / {formatNumber(counts.total)} talabaning yuzi tasdiqlangan
            </p>
          </div>
          <div className="relative mt-5">
            <ProgressBar value={pct} tone={enrollTone(counts.pct)} size="md" ariaLabel="Yuz topshirish progressi" />
            {institute && (
              <div className="absolute -top-1 bottom-0 flex flex-col items-center" style={{ left: `${INSTITUTE_READY_PCT}%` }} aria-hidden="true">
                <span className="h-4 w-px bg-fg/50" />
              </div>
            )}
          </div>
          <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted">
            {institute ? (
              <span>
                <span className="font-medium text-fg">{INSTITUTE_READY_PCT}%</span> dan keyin talabalar davomati ko&apos;rsatila boshlaydi
              </span>
            ) : (
              <span>Guruhda 50% dan oshsa davomat ko&apos;rinadi</span>
            )}
            <span>
              Qoldi: <span className="font-semibold tabular-nums text-fg">{formatNumber(remaining)}</span>
              {counts.pending > 0 && <span className="text-info"> · {formatNumber(counts.pending)} tasdiq kutmoqda</span>}
            </span>
          </div>
          <p className="mt-5 max-w-2xl text-[13px] leading-relaxed text-muted">
            Kamera talabani faqat yuzi tizimda bo&apos;lsa taniydi. Har guruhga QR kartani chop etib bering — talaba telefonida 1 daqiqada topshiradi,
            shundan so&apos;ng davomat o&apos;zi yuritiladi.
          </p>
        </div>

        <div className="flex flex-col gap-3 rounded-card bg-surface-2 p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-fg">
              <Target size={15} className="text-muted" aria-hidden="true" />
              Maqsad sanasi
            </span>
            <DatePicker value={targetDate} onChange={setTargetDate} min={today} max={null} size="sm" ariaLabel="Maqsad sanasi" quick={false} stepper={false} compact />
          </div>
          <Fact icon={Gauge} label="Kuniga kerak">
            {/* "—" hech narsa tushuntirmasdi: sabab — maqsad sanasi qo'yilmagan. */}
            {perDay === null ? <span className="font-normal text-muted">maqsad sanasini tanlang</span> : `${formatNumber(perDay)} ta yuz`}
          </Fact>
          {institute && (
            <>
              <Fact icon={TrendingUp} label="Joriy sur'at">
                {pace ? `~${formatNumber(Math.round(pace.perDay * 10) / 10)} / kun` : <span className="text-muted">ertadan hisoblanadi</span>}
              </Fact>
              <Fact icon={CalendarCheck2} label="Shu sur'atda tugaydi">
                {remaining === 0 ? 'Tugadi' : eta ? formatUzDate(eta, { year: false }) : <span className="font-normal text-muted">sur'at nolga teng</span>}
              </Fact>
              {eta && targetDate && remaining > 0 && (
                <p className={cn('text-xs font-medium', eta <= targetDate ? 'text-success' : 'text-danger')}>
                  {eta <= targetDate ? 'Maqsadga ulguriladi' : "Maqsadga ulgurilmaydi — sur'atni oshirish kerak"}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function Fact({ icon: Icon, label, children }: { icon: typeof Gauge; label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border pt-3 text-[13px]">
      <span className="inline-flex items-center gap-1.5 text-muted">
        <Icon size={15} aria-hidden="true" />
        {label}
      </span>
      <span className="font-semibold tabular-nums text-fg">{children}</span>
    </div>
  );
}

function FacultyEnrollCard({ faculty, to }: { faculty: EnrollCounts & { id: string | null; name: string }; to: string }) {
  const remaining = faculty.total - faculty.confirmed;
  return (
    <Link
      to={to}
      className={cn(
        'group flex min-w-0 flex-col gap-3 rounded-card border border-border bg-surface p-4 shadow-card transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-border-strong hover:shadow-pop sm:p-5',
        focusRing,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 truncate text-base font-semibold text-fg">{faculty.name}</h3>
        <span className="text-lg font-semibold tabular-nums text-fg">{formatPercent(faculty.pct)}</span>
      </div>
      <ProgressBar value={faculty.pct ?? 0} tone={enrollTone(faculty.pct)} ariaLabel={`${faculty.name}: ${formatPercent(faculty.pct)}`} />
      <p className="text-[13px] text-muted">
        <span className="font-semibold tabular-nums text-fg">{formatNumber(faculty.confirmed)}</span> / {formatNumber(faculty.total)} topshirdi
      </p>
      <span className="mt-auto inline-flex items-center gap-1 text-[13px] font-medium text-primary">
        {remaining > 0 ? `${formatNumber(remaining)} talabani yig'ish` : "Davomatni ko'rish"}
        <ChevronRight size={15} className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
      </span>
    </Link>
  );
}
