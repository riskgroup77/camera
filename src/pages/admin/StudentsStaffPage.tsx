import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Briefcase,
  CalendarCheck,
  ChevronLeft,
  ChevronRight,
  Clock,
  Combine,
  Copy,
  Download,
  GraduationCap,
  Pencil,
  Plus,
  ShieldQuestion,
  Trash2,
} from 'lucide-react';
import {
  Avatar,
  Button,
  ButtonLink,
  CodeText,
  ConfirmDialog,
  DataTable,
  ErrorState,
  IconButton,
  IntelPanel,
  MicroLabel,
  Page,
  FilterBar,
  Select,
  StatusLamp,
  filterActiveCount,
  resetFilterFields,
  SkeletonTiles,
  Tabs,
  cn,
  focusRing,
  formatNumber,
  useToast,
  useUrlTab,
  type DataTableColumn,
  type FilterFieldEntry,
  type IntelStatus,
  type TabItem,
} from '../../ui';
import AddStudentStaffModal from '../../components/admin/AddStudentStaffModal';
import EditStudentStaffModal from '../../components/admin/EditStudentStaffModal';
import BiometricsTimeLookupModal from '../../components/admin/BiometricsTimeLookupModal';
import ExportPeopleModal from '../../components/admin/ExportPeopleModal';
import DuplicatePeopleModal from '../../components/admin/DuplicatePeopleModal';
import MergePeopleModal from '../../components/admin/MergePeopleModal';
import SelfEnrollmentReviewModal from '../../components/admin/SelfEnrollmentReviewModal';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { RAG_LABEL, RAG_LETTER, RAG_TEXT, RATE_RAG, rag } from '../../ui/rag';
import { NO_FACULTY_KEY, NO_FACULTY_LABEL, PERSON_LABELS, STATUS_FILTERS, type PersonType, type StatusFilter } from '../../lib/peopleFilters';
import { situationPaths } from '../../lib/situationApi';
import { usePersistedState } from '../../lib/usePersistedState';
import { invalidateServerPageCache, useServerPage } from '../../lib/useServerPage';
import type { BiometricsCoverage, StudentStaffRecord } from '../../types';

/** name — F.I.Sh. (A–Z); faculty — fakultet, keyin F.I.Sh.; confirmed — oxirgi tasdiqlaganlar birinchi. */
type Sort = 'name' | 'faculty' | 'confirmed';
type Overview = Record<PersonType, BiometricsCoverage>;

/** Yuz holati — chiroq: rang yolg'iz emas, yonida so'z turadi. */
const BIOMETRICS_META: Record<StudentStaffRecord['biometricsStatus'], { label: string; status: IntelStatus }> = {
  tasdiqlangan: { label: 'Tasdiqlangan', status: 'ok' },
  kutilmoqda: { label: 'Kutilmoqda', status: 'warn' },
  yoq: { label: 'Tasdiqlanmagan', status: 'alert' },
};

const PAGE_SIZES = [10, 25, 50];
/** Backend: o'zini o'zi ro'yxatdan o'tkazib, tasdiq kutayotganlar. */
const AWAITING_APPROVAL_FILTER = 'tasdiq_kutmoqda';

const PERSON_TABS: TabItem<PersonType>[] = [
  { id: 'xodim', label: PERSON_LABELS.xodim, icon: Briefcase },
  { id: 'talaba', label: PERSON_LABELS.talaba, icon: GraduationCap },
];

/**
 * Qamrov ko'rsatkichi — bosiladigan o'lchov: yorliq, son va (foiz
 * bo'lsa) svetofor hukmi. Ilgari bu StatTile edi; endi hujjat
 * o'lchovi, lekin bosilishi va yorliqlari o'zgarmagan.
 */
function CoverageReadout({
  label,
  value,
  percent,
  onClick,
}: {
  label: string;
  value: string;
  /** Faqat foiz svetofor oladi: xom sanoq yaxshimi-yomonmi — bo'linma hajmisiz aytib bo'lmaydi. */
  percent?: number | null;
  onClick: () => void;
}) {
  const tone = percent === undefined ? null : rag(percent, RATE_RAG);
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('flex min-w-0 flex-col gap-0.5 px-3 py-2 text-left hover:bg-primary-soft', focusRing)}
    >
      <MicroLabel>{label}</MicroLabel>
      <span className="flex items-baseline gap-1.5">
        <span className={cn('intel-code text-[20px] font-semibold leading-none', tone ? RAG_TEXT[tone] : 'text-fg')}>{value}</span>
        {tone && (
          <span className={cn('intel-code text-[10px] font-bold', RAG_TEXT[tone])} title={RAG_LABEL[tone]}>
            {RAG_LETTER[tone]}
          </span>
        )}
      </span>
    </button>
  );
}

function Pager({
  page,
  totalPages,
  total,
  pageSize,
  onPage,
  onPageSize,
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted">
      <div className="flex items-center gap-2">
        <CodeText className="text-[12px]">
          {formatNumber(from)}–{formatNumber(to)} / {formatNumber(total)} ta
        </CodeText>
        <Select
          value={String(pageSize)}
          onChange={(value) => onPageSize(Number(value))}
          options={PAGE_SIZES.map((size) => ({ value: String(size), label: `${size} tadan` }))}
          ariaLabel="Sahifadagi yozuvlar soni"
          size="sm"
          className="w-auto"
        />
      </div>
      {totalPages > 1 && (
        <div className="flex items-center gap-1">
          <IconButton icon={ChevronLeft} label="Oldingi sahifa" size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)} />
          <CodeText className="px-2 text-[12px] font-semibold text-fg">
            {page} / {totalPages}
          </CodeText>
          <IconButton icon={ChevronRight} label="Keyingi sahifa" size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => onPage(page + 1)} />
        </div>
      )}
    </div>
  );
}

/** Qator ichidagi tugmalar (telefondagi kartada ham) — bosish qatorga o'tmasin. */
function RowActions({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-1" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      {children}
    </div>
  );
}

export default function StudentsStaffPage() {
  const { token, role } = useAuth();
  const { can } = usePermissions();
  // Eksport faylida JSHSHIR bor — alohida huquq (server ham tekshiradi).
  const canExport = can('exportData', role);
  const toast = useToast();
  // ?search=<matn>&tur=talaba|xodim — boshqa sahifalardan (turniket jurnali,
  // tanilmagan kartalar) aniq odamga havola. `tur` — sahifa tabi ham.
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab] = useUrlTab(PERSON_TABS, { param: 'tur', defaultTab: 'xodim' });
  const [facultyFilter, setFacultyFilter] = useState('');
  const [courseFilter, setCourseFilter] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '');
  const [sort, setSort] = useState<Sort>('name');
  const [pageSizeChoice, setPageSizeChoice] = usePersistedState<number>('odamlar.sahifaHajmi', 10);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewError, setOverviewError] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [dupOpen, setDupOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<StudentStaffRecord | null>(null);
  const [deleting, setDeleting] = useState<StudentStaffRecord | null>(null);
  // Qo'lda birlashtirish: kim bilan va (tahrirlashdan kelsa) qaysi JSHSHIR bo'yicha qidiriladi.
  const [mergeTarget, setMergeTarget] = useState<{ person: StudentStaffRecord; search: string } | null>(null);
  const [reviewing, setReviewing] = useState<StudentStaffRecord | null>(null);
  const [awaitingOnly, setAwaitingOnly] = useState(false);
  const [lookup, setLookup] = useState<{ open: boolean; person: StudentStaffRecord | null }>({ open: false, person: null });

  const isStudents = tab === 'talaba';
  const pageSize = PAGE_SIZES.includes(pageSizeChoice) ? pageSizeChoice : 10;

  // ?search= bir marta o'qiladi va URL'dan olib tashlanadi. Ilgari u faqat
  // birinchi renderda olinardi: komponent tirik turganda boshqa sahifadan
  // ikkinchi marta kelinsa qidiruv o'zgarmasdi; qidiruvni tozalagandan
  // keyin sahifa yangilansa esa eski so'z URL'dan qaytib kelardi.
  useEffect(() => {
    const fromUrl = searchParams.get('search');
    if (fromUrl === null) return;
    setSearch(fromUrl);
    const next = new URLSearchParams(searchParams);
    next.delete('search');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // Bo'lim almashganda bo'limga xos filtrlar tozalanadi. Holat filtri
  // ataylab saqlanadi: "ro'yxatdan o'tmaganlar"ni ikkala bo'limda ketma-ket
  // ko'rish tez-tez uchraydigan ish.
  const previousTab = useRef(tab);
  useEffect(() => {
    if (previousTab.current === tab) return;
    previousTab.current = tab;
    setFacultyFilter('');
    setCourseFilter(null);
    setSearch('');
  }, [tab]);

  const {
    items: records,
    page,
    setPage,
    totalPages,
    total,
    loading,
    refreshing,
    error,
    reload,
  } = useServerPage<StudentStaffRecord>(
    '/api/students-staff/search',
    {
      type: tab,
      faculty: facultyFilter || undefined,
      course: isStudents && courseFilter ? String(courseFilter) : undefined,
      biometricsStatus: awaitingOnly ? AWAITING_APPROVAL_FILTER : statusFilter || undefined,
      search: search.trim() || undefined,
      sort,
    },
    pageSize,
    { post: true },
  );

  // Qamrov ro'yxatdan MUSTAQIL: u filtrlangan sahifani emas, butun bo'limni
  // ko'rsatadi. Ikkala tur bitta so'rovda — tablardagi sonlar ham shundan.
  // Bekor qilish bayrog'i: sahifadan chiqilgandan keyin yoki yangi so'rov
  // ketgandan keyin kech kelgan javob eskirgan statistikani yozib
  // qo'ymasligi uchun. Ilgari har `refresh()` yangi so'rov ochar, javoblar
  // qaysi kelsa o'sha yozilardi.
  const overviewRun = useRef(0);
  const loadOverview = useCallback(() => {
    if (!token) return;
    const run = ++overviewRun.current;
    api
      .get<Overview>('/api/students-staff/overview', token)
      .then((data) => {
        if (run !== overviewRun.current) return;
        setOverview(data);
        setOverviewError(false);
      })
      .catch(() => {
        if (run === overviewRun.current) setOverviewError(true);
      });
  }, [token]);

  useEffect(() => {
    loadOverview();
    return () => {
      overviewRun.current += 1;
    };
  }, [loadOverview]);


  function refresh() {
    invalidateServerPageCache('/api/students-staff');
    reload();
    loadOverview();
  }

  const current = overview?.[tab] ?? null;
  const statusCount = (key: StatusFilter): number | undefined => {
    if (!current) return undefined;
    if (key === 'tasdiqlangan') return current.confirmed;
    if (key === 'tasdiqlanmagan') return current.missing + current.pending;
    return current.total;
  };
  const awaitingCount = current?.awaitingApproval ?? 0;
  const [approveAllOpen, setApproveAllOpen] = useState(false);

  const tabs = useMemo<TabItem<PersonType>[]>(
    () => PERSON_TABS.map((t) => ({ ...t, count: overview?.[t.id]?.total ?? null })),
    [overview],
  );

  function pickStatus(next: StatusFilter) {
    setAwaitingOnly(false);
    setStatusFilter(next);
  }

  const columns: DataTableColumn<StudentStaffRecord>[] = [
    {
      key: 'name',
      header: 'F.I.Sh.',
      sortValue: () => null,
      cell: (person) => (
        <span className="flex min-w-0 items-center gap-3">
          <Avatar name={person.fullName} src={person.biometricPhotoUrl} size="sm" />
          <Link
            to={situationPaths.person(person.id)}
            onClick={(e) => e.stopPropagation()}
            className={cn('min-w-0 truncate rounded font-medium text-fg hover:text-primary hover:underline', focusRing)}
          >
            {person.fullName}
          </Link>
        </span>
      ),
    },
    {
      key: 'faculty',
      header: 'Fakultet',
      sortValue: () => null,
      cell: (person) => <span className="text-muted">{person.faculty || NO_FACULTY_LABEL}</span>,
    },
    ...(isStudents
      ? [
          {
            key: 'course',
            header: 'Kurs',
            cell: (person: StudentStaffRecord) => (person.course ? `${person.course}-kurs` : <span className="text-subtle">—</span>),
          },
          {
            key: 'group',
            header: 'Guruh',
            cell: (person: StudentStaffRecord) => {
              const group = person.group || (person.course ? null : person.groupOrPosition);
              if (!group) return <span className="text-subtle">—</span>;
              const name = person.group ? (
                <Link
                  to={situationPaths.group(person.group)}
                  onClick={(e) => e.stopPropagation()}
                  className={cn('rounded text-fg hover:text-primary hover:underline', focusRing)}
                >
                  {group}
                </Link>
              ) : (
                group
              );
              if (!person.reportedGroup) return name;
              // HEMIS'da topilmagan: bo'limdan so'rash uchun o'zi yozgani ham ko'rinsin.
              return (
                <span className="flex flex-col">
                  {name}
                  <span className="text-[11px] text-muted">yozgani: {person.reportedGroup}</span>
                </span>
              );
            },
          },
        ]
      : [
          {
            key: 'position',
            header: "Bo'linma / Lavozim",
            cell: (person: StudentStaffRecord) => (
              <span className="block min-w-0">
                <span className="block truncate text-fg">{person.orgUnit || person.groupOrPosition || '—'}</span>
                {person.position && <span className="block truncate text-[12px] text-muted">{person.position}</span>}
              </span>
            ),
          },
        ]),
    {
      key: 'status',
      header: 'Yuz holati',
      width: '9.5rem',
      cell: (person) => (
        <span className="flex flex-col gap-0.5">
          {person.awaitingApproval ? (
            <StatusLamp status="warn" label="Tasdiq kutmoqda" />
          ) : (
            <StatusLamp status={BIOMETRICS_META[person.biometricsStatus].status} label={BIOMETRICS_META[person.biometricsStatus].label} />
          )}
          {person.biometricsStatus !== 'yoq' && (person.photoAngles ?? 0) < 3 && (
            <span className="text-[11px] text-warning" title="3 tomonlama (old, chap, o'ng) ro'yxatdan o'tmagan — havola orqali qayta o'tishi kerak">
              {person.photoAngles ?? 0}/3 burchak
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'confirmed',
      header: 'Tasdiqlangan',
      sortValue: () => null,
      sortFirst: 'desc',
      hideOnMobile: true,
      cell: (person) =>
        person.confirmedLabel ? (
          <CodeText className="whitespace-nowrap text-[12px] text-muted">{person.confirmedLabel}</CodeText>
        ) : person.biometricsStatus === 'tasdiqlangan' ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setLookup({ open: true, person });
            }}
            title="Vaqt yozilmagan — yuz rasmi saqlangan paytdan tiklanadi"
            className={cn('rounded text-xs font-medium text-primary underline decoration-dotted underline-offset-2 hover:text-primary/80', focusRing)}
          >
            Vaqtini aniqlash
          </button>
        ) : (
          <span className="text-subtle">—</span>
        ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">Amallar</span>,
      mobileLabel: 'Amallar',
      align: 'right',
      cell: (person) => (
        <RowActions>
          {person.awaitingApproval && (
            <Button size="sm" variant="soft" icon={ShieldQuestion} onClick={() => setReviewing(person)}>
              Ko&apos;rib chiqish
            </Button>
          )}
          <ButtonLink to={situationPaths.person(person.id)} size="sm" variant="ghost" icon={CalendarCheck} title="Davomat va profil">
            Davomat
          </ButtonLink>
          <IconButton icon={Pencil} label={`${person.fullName} — tahrirlash`} size="sm" onClick={() => setEditing(person)} />
          <IconButton
            icon={Combine}
            label={`${person.fullName} — ikkinchi yozuvi bilan birlashtirish`}
            size="sm"
            onClick={() => setMergeTarget({ person, search: '' })}
          />
          <IconButton icon={Trash2} label={`${person.fullName} — ro'yxatdan o'chirish`} size="sm" variant="danger" onClick={() => setDeleting(person)} />
        </RowActions>
      ),
    },
  ];

  const filterFields: FilterFieldEntry[] = [
    {
      kind: 'search',
      value: search,
      onChange: setSearch,
      placeholder: `${isStudents ? 'Talaba' : 'Xodim'} F.I.Sh. yoki JSHSHIR…`,
      ariaLabel: `${PERSON_LABELS[tab]}ni qidirish`,
    },
    {
      kind: 'select',
      value: facultyFilter,
      onChange: setFacultyFilter,
      placeholder: 'Barcha fakultetlar',
      ariaLabel: 'Fakultet',
      options: (current?.byFaculty ?? []).map((row) => ({
        value: row.faculty === NO_FACULTY_LABEL ? NO_FACULTY_KEY : row.faculty,
        label: `${row.faculty} (${formatNumber(row.total)})`,
      })),
    },
    // Kurs faqat talabalarda.
    isStudents && {
      kind: 'select',
      value: courseFilter ? String(courseFilter) : '',
      onChange: (value: string) => setCourseFilter(value ? Number(value) : null),
      placeholder: 'Barcha kurslar',
      ariaLabel: 'Kurs',
      options: (current?.byCourse ?? [])
        .filter((row) => row.courseNumber !== null)
        .map((row) => ({ value: String(row.courseNumber), label: `${row.course} (${formatNumber(row.total)})` })),
    },
    // Yuz holati — segmentli tablar; faolligi va tozalanishi shu yerda.
    {
      kind: 'custom',
      active: Boolean(statusFilter) || awaitingOnly,
      onClear: () => {
        setStatusFilter('');
        setAwaitingOnly(false);
      },
      render: (
        <Tabs
          variant="segmented"
          ariaLabel="Yuz holati"
          tabs={STATUS_FILTERS.map((f) => ({ id: f.key, label: f.label, count: statusCount(f.key) ?? null }))}
          value={awaitingOnly ? ('__awaiting__' as StatusFilter) : statusFilter}
          onChange={pickStatus}
        />
      ),
    },
  ];
  const activeFilters = filterActiveCount(filterFields);
  const resetFilters = () => resetFilterFields(filterFields);
  const toolbar = <FilterBar fields={filterFields} />;


  return (
    <Page
      title="Shaxslar reestri"
      tabs={tabs}
      tabParam="tur"
      defaultTab="xodim"
      toolbar={toolbar}
      actions={
        <>
          <Button icon={Clock} onClick={() => setLookup({ open: true, person: null })} disabled={!token}>
            Tasdiq vaqti
          </Button>
          {canExport && (
            <Button icon={Download} onClick={() => setExportOpen(true)} disabled={!token}>
              Yuklab olish
            </Button>
          )}
          <Button icon={Copy} onClick={() => setDupOpen(true)} disabled={!token}>
            Dublikatlar
          </Button>
          <Button variant="primary" icon={Plus} onClick={() => setModalOpen(true)}>
            Yangi qo&apos;shish
          </Button>
        </>
      }
    >
      {overviewError && !current && (
        <ErrorState title="Qamrov olinmadi" onRetry={loadOverview} />
      )}

      {!current && !overviewError && <SkeletonTiles count={4} className="xl:grid-cols-4" />}

      {/* Statistika yangilanmagan bo'lsa jim turmaymiz: eski raqamlar
          to'g'riday ko'rinib qolardi. */}
      {overviewError && current && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-2 border border-warning/50 bg-warning-soft px-3 py-2 text-[13px] text-fg">
          <span>Raqamlar eskirgan.</span>
          <Button size="sm" onClick={loadOverview}>
            Qayta urinish
          </Button>
        </div>
      )}

      {current && (
        <IntelPanel title="Yuz qamrovi" brackets={false}>
          <div className="grid grid-cols-3 gap-px bg-border">
            <span className="bg-surface">
              <CoverageReadout label="Jami" value={formatNumber(current.total)} onClick={() => pickStatus('')} />
            </span>
            <span className="bg-surface">
              <CoverageReadout
                label="Tasdiqlangan"
                value={formatNumber(current.confirmed)}
                percent={current.percent}
                onClick={() => pickStatus('tasdiqlangan')}
              />
            </span>
            {/* «Tasdiqlanmagan» filtri kutilayotganlarni ham qamrab oladi. */}
            <span className="bg-surface">
              <CoverageReadout
                label="Tasdiqlanmagan"
                value={formatNumber(current.missing + current.pending)}
                onClick={() => pickStatus('tasdiqlanmagan')}
              />
            </span>
          </div>
        </IntelPanel>
      )}

      {(awaitingCount > 0 || awaitingOnly) && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 border border-warning/50 bg-warning-soft px-3 py-2">
          <span className="flex min-w-0 items-start gap-2.5 text-[13px] text-fg">
            <ShieldQuestion size={16} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
            {awaitingCount > 0
              ? `${formatNumber(awaitingCount)} kishi tasdiq kutmoqda.`
              : 'Tasdiq kutayotganlar qolmadi.'}
          </span>
          <span className="flex gap-2">
            {awaitingCount > 0 && (
              <Button size="sm" variant="primary" onClick={() => setApproveAllOpen(true)}>
                Hammasini tasdiqlash
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAwaitingOnly((value) => !value);
                setPage(1);
              }}
            >
              {awaitingOnly ? "Butun ro'yxat" : "Ko'rib chiqish"}
            </Button>
          </span>
        </div>
      )}

      <IntelPanel title={PERSON_LABELS[tab]} right={<MicroLabel>{formatNumber(total)} ta</MicroLabel>}>
      <DataTable
        ariaLabel={PERSON_LABELS[tab]}
        columns={columns}
        rows={records}
        rowKey={(person) => person.id}
        loading={loading && records.length === 0}
        loadingRows={Math.min(pageSize, 10)}
        error={error}
        onRetry={refresh}
        dense
        manualSort
        sort={{ key: sort, dir: sort === 'confirmed' ? 'desc' : 'asc' }}
        onSortChange={(next) => {
          if (next && next.key !== sort) setSort(next.key as Sort);
        }}
        maxHeight="none"
        className={cn('transition-opacity', refreshing && 'opacity-70')}
        emptyTitle={`${isStudents ? 'Talaba' : 'Xodim'} topilmadi`}
        emptyAction={
          activeFilters > 0 ? (
            <Button onClick={resetFilters}>Filtrlarni tozalash</Button>
          ) : (
            <Button variant="primary" icon={Plus} onClick={() => setModalOpen(true)}>
              Yangi qo&apos;shish
            </Button>
          )
        }
        footer={
          !error && records.length > 0 ? (
            <Pager
              page={page}
              totalPages={totalPages}
              total={total}
              pageSize={pageSize}
              onPage={setPage}
              onPageSize={(size) => {
                setPageSizeChoice(size);
                setPage(1);
              }}
            />
          ) : undefined
        }
      />
      </IntelPanel>

      <DuplicatePeopleModal
        open={dupOpen}
        onClose={() => setDupOpen(false)}
        onMerged={refresh}
      />

      <ExportPeopleModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        defaults={{ type: tab, faculty: facultyFilter, course: courseFilter, status: statusFilter, search }}
        coverage={{ xodim: overview?.xodim ?? null, talaba: overview?.talaba ?? null }}
      />
      <BiometricsTimeLookupModal open={lookup.open} person={lookup.person} onClose={() => setLookup({ open: false, person: null })} />
      <AddStudentStaffModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAdd={(record) => {
          refresh();
          toast.success(`${record.fullName} reestrga qo'shildi`);
        }}
      />
      {/* O'chirish qaytarib bo'lmaydi va odamning butun tarixini olib
          ketadi, shuning uchun tasdiqlash oynasida AYNAN nima yo'qolishi
          yozilgan — "rostdanmi?" degan savolning o'zi yetarli emas. */}
      <ConfirmDialog
        open={approveAllOpen}
        title="Hammasini tasdiqlash"
        message={`${formatNumber(awaitingCount)} kishining yuzi tasdiqlanadi va kameralar ularni tanishni boshlaydi. Uch tomondan (old, chap, o'ng) olinmagan yuzlar tasdiqlanmaydi.`}
        confirmLabel="Ha, tasdiqlansin"
        onCancel={() => setApproveAllOpen(false)}
        onConfirm={async () => {
          try {
            const res = await api.post<{ approved: number; skippedAngles: number }>(
              `/api/students-staff/biometrics/approve-all?type=${tab}`,
              {},
              token,
            );
            toast.success(
              `${formatNumber(res.approved)} kishi tasdiqlandi` +
                (res.skippedAngles ? `, ${formatNumber(res.skippedAngles)} tasi 3 tomondan olinmagani uchun qoldi` : ''),
            );
            refresh();
          } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Tasdiqlab bo‘lmadi');
          } finally {
            setApproveAllOpen(false);
          }
        }}
      />
      <ConfirmDialog
        open={!!deleting}
        title="Ro'yxatdan o'chirish"
        message={
          deleting
            ? `${deleting.fullName} ro'yxatdan butunlay o'chiriladi. Bu bilan birga uning davomat yozuvlari, kameradagi tashriflari va yuz ma'lumoti ham o'chadi. Amalni ortga qaytarib bo'lmaydi.`
            : ''
        }
        confirmLabel="Ha, o'chirilsin"
        onCancel={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          await api.del(`/api/students-staff/${deleting.id}`, token);
          const removed = deleting.fullName;
          setDeleting(null);
          // Sahifadagi oxirgi yozuv o'chirilsa, oldingi sahifaga qaytamiz —
          // aks holda ro'yxat bo'sh ko'rinib, "hammasi o'chib ketdi" degan
          // taassurot qoladi.
          if (records.length === 1 && page > 1) setPage(page - 1);
          refresh();
          toast.success(`${removed} ro'yxatdan o'chirildi`);
        }}
      />
      <SelfEnrollmentReviewModal
        record={reviewing}
        onClose={() => setReviewing(null)}
        onDone={(decision, updated) => {
          setReviewing(null);
          refresh();
          toast.success(
            decision === 'approve' ? `${updated.fullName} tasdiqlandi — endi kameralar uni taniydi` : `${updated.fullName} yuzi rad etildi`,
          );
        }}
      />
      <EditStudentStaffModal
        record={editing}
        onClose={() => setEditing(null)}
        onSave={() => {
          setEditing(null);
          refresh();
          toast.success('Saqlandi');
        }}
        onMergeRequest={(pinfl) => {
          if (editing) setMergeTarget({ person: editing, search: pinfl });
          setEditing(null);
        }}
      />
      <MergePeopleModal
        person={mergeTarget?.person ?? null}
        initialSearch={mergeTarget?.search ?? ''}
        onClose={() => setMergeTarget(null)}
        onMerged={refresh}
      />
    </Page>
  );
}
