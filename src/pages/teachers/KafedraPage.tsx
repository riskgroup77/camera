import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { BarChart3, BookOpen, CalendarCheck, Rows3, ScanFace, Table2, Users } from 'lucide-react';
import PdfButton from '../../components/situation/PdfButton';
import { UnitEnrollDrawer } from '../../components/teachers/UnitEnrollDrawer';
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  DataTable,
  DateRangePicker,
  detectPreset,
  EmptyState,
  ErrorState,
  IntelPanel,
  KeyValue,
  MicroLabel,
  Page,
  PageSkeleton,
  SearchInput,
  Select,
  StatusBadge,
  Tabs,
  Toolbar,
  cn,
  formatPercent,
  formatUzRange,
  isIsoDate,
  rangeForPreset,
  useShell,
  useUrlTab,
  type DataTableColumn,
  type DateRangeValue,
  type TabItem,
} from '../../ui';
import { RATE_RAG, rag } from '../../ui/rag';
import { RagLegend, StatusBoard, type BoardItem } from '../../components/hisobot/board';
import { KpiReadout, RateCell, StaleNote, StatusMark, worstFirst } from '../../components/attendance/readout';
import { LessonDrawer } from '../../components/lessons/LessonDrawer';
import { LessonsTable } from '../../components/lessons/LessonsTable';
import { TodayLessons } from '../../components/teachers/TeacherBits';
import { TeacherDayDrawer } from '../../components/teachers/TeacherDayDrawer';
import { useLoader } from '../../components/teachers/useLoader';
import { UnitAnalyticsSection } from '../../components/teachers/UnitAnalyticsSection';
import ReportGate from '../../components/hisobot/ReportGate';
import { getKafedra, getLessons, situationPaths, UNIT_KIND_LABELS, type KafedraDetail, type KafedraTeacher, type Lesson } from '../../lib/situationApi';
import { LESSON_TEACHER_SORTS, matchesName, resolveTeacherSort, sortTeachers, type TeacherSort } from '../../lib/teachersApi';
import { usePersistedState } from '../../lib/usePersistedState';
import { useViewDate } from '../../lib/viewDate';
import type { FixedPreset } from '../../lib/reportPeriods';

type TabId = 'oqituvchilar' | 'tahlil' | 'darslar';
/** Saqlangan eski `'grid'` ("yuzlar") ham taxtaga tushadi. */
type View = 'board' | 'table';

const PERIOD_PRESETS: readonly FixedPreset[] = ['last7', 'last30', 'month'];
const SORT_OPTIONS: { value: TeacherSort; label: string }[] = [
  { value: 'lateness', label: 'Ko‘p kechikkan' },
  { value: 'onTime', label: 'Darsga kam kirgan' },
  { value: 'name', label: 'Ism' },
];
// 30 kunlik dars/davomat yig'indisi og'ir — 5 daqiqada bir yetarli.
const REFRESH_MS = 300_000;

/** Xodimning davr bo'yicha ishga kelish foizi — maxraj YOZUV BOR kunlar
 *  (kelgan + kelmagan). Dam olish va yozuvsiz kunlar hukmga kirmaydi. */
function presenceRate(t: Pick<KafedraTeacher, 'periodPresentDays' | 'periodAbsentDays'>): number | null {
  const decided = t.periodPresentDays + t.periodAbsentDays;
  return decided > 0 ? Math.round((t.periodPresentDays / decided) * 1000) / 10 : null;
}

/** Darsga o'z vaqtida kirish davri URL'da (`?dan=&gacha=`): ilgari u faqat komponent
 *  ichidagi `useState` edi — sahifani yangilash yoki havolani ulashish
 *  tanlangan davrni yo'qotardi va qabul qiluvchi boshqa raqamlarni ko'rardi.
 *  URL'da qiymat bo'lmasa — ko'rilayotgan sanagacha 30 kun. */
function useKafedraPeriod(date: string): [DateRangeValue, (value: DateRangeValue) => void] {
  const [params, setParams] = useSearchParams();
  const from = params.get('dan');
  const to = params.get('gacha');
  const custom = params.get('davr') === 'oraliq';
  const value = useMemo<DateRangeValue>(() => {
    if (isIsoDate(from) && isIsoDate(to) && from <= to) {
      return { from, to, preset: custom ? 'custom' : detectPreset({ from, to }, PERIOD_PRESETS, date) };
    }
    return rangeForPreset('last30', date);
  }, [from, to, custom, date]);

  const setValue = useCallback(
    (next: DateRangeValue) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set('dan', next.from);
          p.set('gacha', next.to);
          if (next.preset === 'custom') p.set('davr', 'oraliq');
          else p.delete('davr');
          return p;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return [value, setValue];
}

export default function KafedraPage() {
  const { departmentId = '' } = useParams();
  const { date, isToday, withDate } = useViewDate();
  const { presentation } = useShell();

  // Darsga o'z vaqtida kirish davri: standart — ko'rilayotgan sanagacha 30 kun.
  const [period, setPeriod] = useKafedraPeriod(date);
  const [view, setView] = usePersistedState<View>('kafedra.view', 'board');
  const [sort, setSort] = usePersistedState<TeacherSort>('kafedra.sort', 'lateness');
  const [search, setSearch] = useState('');
  const [enrollOpen, setEnrollOpen] = useState(false);
  // Boshqa bo'linmaga o'tilganda eski qidiruv so'zi yangi ro'yxatni
  // "Hech kim topilmadi" holatida qoldirmasin.
  useEffect(() => {
    setSearch('');
  }, [departmentId]);

  const periodValid = period.from <= period.to;
  const detailKey = periodValid ? `${departmentId}:${date}:${period.from}:${period.to}` : null;
  const detail = useLoader(
    detailKey,
    (signal) => getKafedra(departmentId, { date, from: period.from, to: period.to }, { signal }),
    { refreshMs: isToday ? REFRESH_MS : undefined, group: `${departmentId}:${date}` },
  );
  const data = detail.data;
  // Dars jadvali kiritilmagan bo'lsa "Darslar" tabi ham, so'rovi ham yo'q.
  // `lessonsScheduled` o'qituvchilar ro'yxati bilan kelgan — qo'shimcha
  // so'rovsiz. Jadval paydo bo'lishi bilan tab o'zi qaytadi.
  const scheduledLessons = useMemo(
    () => (data?.teachers ?? []).reduce((sum, t) => sum + t.lessonsScheduled, 0),
    [data?.teachers],
  );
  const lessons = useLoader(
    scheduledLessons > 0 ? `${departmentId}:${date}` : null,
    (signal) => getLessons({ date, departmentId, pageSize: 500 }, { signal }),
    { refreshMs: isToday ? REFRESH_MS : undefined },
  );

  // Dars jadvali yo'q bo'lsa dars asosidagi tartiblar ro'yxatdan chiqadi
  // (saqlangan tanlov ham "kechikish"ga qaytadi — Select bo'sh qolmasin).
  // `data` kelmaguncha "dars jadvali yo'q" deb hisoblamaymiz: aks holda
  // yuklanish paytida "Darsga kam kirganlar" tartibi ro'yxatdan tushib,
  // Select o'zi "kechikish"ga sakrab, keyin qaytib kelardi.
  const periodLessons = data?.period.lessons ?? 0;
  const hasPeriodLessonsForSort = data ? periodLessons > 0 : LESSON_TEACHER_SORTS.includes(sort);
  const sortOptions = hasPeriodLessonsForSort ? SORT_OPTIONS : SORT_OPTIONS.filter((o) => !LESSON_TEACHER_SORTS.includes(o.value));
  const effectiveSort = resolveTeacherSort(sort, hasPeriodLessonsForSort);

  // Tab hisoblagichi qidiruvdan keyin ro'yxatdagi qatorlar soniga teng
  // bo'lsin: ilgari u doim bo'linmadagi JAMI xodimni ko'rsatib, ro'yxatda
  // 2 kishi turganda tabda "48" yozilardi.
  const visibleTeachers = useMemo(() => {
    const list = data?.teachers ?? [];
    return search.trim() ? list.filter((t) => matchesName(t.fullName, search)).length : list.length;
  }, [data?.teachers, search]);
  const tabs: TabItem<TabId>[] = [
    { id: 'oqituvchilar', label: "O'qituvchilar", icon: Users, count: data ? visibleTeachers : null },
    { id: 'tahlil', label: 'Tahlil', icon: BarChart3 },
    // Tab ro'yxatda bo'lmasa `?tab=darslar` standart tabga tushadi (resolveTab).
    ...(scheduledLessons > 0
      ? [{ id: 'darslar' as const, label: 'Darslar', icon: BookOpen, count: lessons.data?.total ?? null }]
      : []),
  ];
  const [tab] = useUrlTab(tabs, { defaultTab: 'oqituvchilar' });

  const notFound = detail.error && !data && /topilmadi|404/i.test(detail.error);
  const title = data?.name ?? (notFound ? "Bo'linma topilmadi" : "Bo'linma");
  const crumbs = [{ label: "Xodimlar va o'qituvchilar", to: '/oqituvchilar' }];
  const effectiveView: View = presentation || view !== 'table' ? 'board' : 'table';

  if (detail.loading && !data && !detail.error) {
    return (
      <Page title="Bo'linma" breadcrumbs={[...crumbs, { label: "Bo'linma" }]}>
        <PageSkeleton />
      </Page>
    );
  }

  return (
    <Page
      title={title}
      subtitle={
        data ? [data.building, `${data.today.total} xodim`, data.date].filter(Boolean).join(' · ') : undefined
      }
      titleAddon={
        data ? (
          <Badge tone={data.unassigned ? 'warning' : data.kind === 'kafedra' ? 'primary' : data.kind === 'dekanat' ? 'info' : 'neutral'}>
            {data.unassigned ? 'Biriktirilmagan' : (UNIT_KIND_LABELS[data.kind] ?? data.kind)}
          </Badge>
        ) : undefined
      }
      breadcrumbs={[...crumbs, { label: title }]}
      tabs={data ? tabs : undefined}
      defaultTab="oqituvchilar"
      toolbar={
        data && tab === 'oqituvchilar' ? (
          <Toolbar
            end={
              !presentation && (
                <Tabs
                  variant="segmented"
                  size="sm"
                  value={effectiveView}
                  onChange={setView}
                  ariaLabel="Ko'rinish"
                  tabs={[
                    { id: 'board' as const, label: 'Taxta', icon: Rows3 },
                    { id: 'table' as const, label: 'Jadval', icon: Table2 },
                  ]}
                />
              )
            }
          >
            <SearchInput value={search} onChange={setSearch} placeholder="Ism bo'yicha…" ariaLabel="O'qituvchini qidirish" />
            {data.teachers.some((t) => t.biometricsStatus !== 'tasdiqlangan') && (
              <Button size="sm" variant="soft" icon={ScanFace} onClick={() => setEnrollOpen(true)}>
                {`Yuzsiz: ${data.teachers.filter((t) => t.biometricsStatus !== 'tasdiqlangan').length}`}
              </Button>
            )}
            <PdfButton
              path="/api/situation/pdf/people"
              params={{ type: 'xodim', departmentId, date, search: search || undefined }}
              filename={`${title}-${date}.pdf`}
            />
            <Select value={effectiveSort} onChange={(v) => setSort(v as TeacherSort)} options={sortOptions} label="Tartib:" ariaLabel="Tartiblash" />
            {!presentation && <DateRangePicker value={period} onChange={setPeriod} presets={PERIOD_PRESETS} size="sm" showSummary={false} />}
          </Toolbar>
        ) : data && tab === 'tahlil' && !presentation ? (
          <Toolbar>
            <DateRangePicker value={period} onChange={setPeriod} presets={PERIOD_PRESETS} size="sm" />
          </Toolbar>
        ) : undefined
      }
    >
      {/* Davr almashganda yangi so'rov yiqilsa ekranda ESKI davr raqamlari
          qolardi — hech qanday belgisiz. Endi eskirgani aytiladi. */}
      {data && detail.error && <StaleNote message={detail.error} onRetry={detail.reload} />}
      {!periodValid ? (
        // Oraliq teskari kiritilganda sahifa avval butunlay bo'sh qolardi —
        // hech qanday xabar ham, ma'lumot ham yo'q edi.
        <EmptyState
          icon={CalendarCheck}
          compact
          title="Davr noto'g'ri"
          description="Boshlanish sanasi tugashdan keyin turibdi."
        />
      ) : detail.error && !data ? (
        notFound ? (
          <EmptyState
            icon={Users}
            title="Bo'linma topilmadi"
            description="Havola eskirgan bo'lishi mumkin."
            action={
              <ButtonLink to="/oqituvchilar" variant="secondary">
                Ro&apos;yxatga qaytish
              </ButtonLink>
            }
          />
        ) : (
          <ErrorState variant="block" message={detail.error} onRetry={detail.reload} />
        )
      ) : data ? (
        <div className="flex min-w-0 flex-col gap-3">
          {tab !== 'tahlil' && (
            <IntelPanel title="Asosiy ko'rsatkichlar">
              <KafedraKpis data={data} />
            </IntelPanel>
          )}

          {tab === 'oqituvchilar' ? (
            // key: boshqa bo'linmaga o'tilganda ochiq drawer va tanlov
            // eski bo'linmaning xodimida qolib ketmasin.
            <TeachersSection key={data.id} data={data} date={date} view={effectiveView} sort={effectiveSort} search={search} withDate={withDate} />
          ) : tab === 'tahlil' ? (
            <ReportGate>
              <UnitAnalyticsSection unitId={data.id} unitName={data.name} kind={data.kind} from={period.from} to={period.to} />
            </ReportGate>
          ) : (
            <LessonsSection
              rows={lessons.data?.items ?? []}
              total={lessons.data?.total ?? 0}
              loading={lessons.loading}
              error={lessons.data ? null : lessons.error}
              onRetry={lessons.reload}
            />
          )}

        </div>
      ) : null}
      <UnitEnrollDrawer unit={data ?? null} open={enrollOpen} onClose={() => setEnrollOpen(false)} withDate={withDate} />
    </Page>
  );
}

function KafedraKpis({ data }: { data: KafedraDetail }) {
  const t = data.today;
  const p = data.period;
  const checked = p.onTime + p.late + p.missed;
  const hasLessons = p.lessons > 0;
  // "Bugun" faqat bugungi kun ko'rilayotganda — ?sana= bilan o'tgan kunga
  // o'tilganda ko'rsatkichlar baribir "Bugun" derdi.
  const dayWord = data.isToday ? 'Bugun' : 'Shu kuni';
  // Foiz maxraji — holati aniqlangan xodimlar (keldi + kelmadi + hali
  // kelmagan): yuzi ro'yxatdan o'tmaganlar foizga umuman kirmaydi. Katta
  // sondagi maxraj ham AYNAN shu — aks holda "10 / 20" yonida 83% turardi.
  const decided = t.present + t.absent + t.notYet;
  return (
    <KpiReadout
      className={hasLessons ? 'lg:grid-cols-4' : 'lg:grid-cols-2'}
      items={[
        {
          label: `${dayWord} keldi`,
          value: t.present,
          unit: `/ ${decided}`,
          rate: t.rate,
          // Maxraj jami xodimdan kichik — sababsiz u tushunarsiz qoladi.
          hint: `Holati aniq ${decided} xodimdan`,
        },
        {
          label: `${dayWord} kech keldi`,
          value: t.late,
          unit: 'kishi',
        },
        ...(hasLessons
          ? [
              {
                label: "Darsga o'z vaqtida",
                value: formatPercent(p.onTimeRate),
                rate: p.onTimeRate,
                hint: `${checked} darsdan ${p.onTime} tasi`,
              },
              {
                label: 'Kech / kirmagan',
                value: `${p.late} / ${p.missed}`,
                unit: `/ ${p.lessons}`,
              },
            ]
          : []),
      ]}
    />
  );
}

function TeachersSection({ data, date, view, sort, search, withDate }: { data: KafedraDetail; date: string; view: View; sort: TeacherSort; search: string; withDate: (path: string) => string }) {
  // Dars jadvali yo'q bo'lsa dars ustunlari/qatorlari chizilmaydi:
  // har satrda "Darsi yo'q" va har joyda "—" turishining ma'nosi yo'q.
  const hasTodayLessons = data.teachers.some((t) => t.lessonsScheduled > 0);
  const hasPeriodLessons = data.period.lessons > 0;
  const [selected, setSelected] = useState<KafedraTeacher | null>(null);

  const rows = useMemo(() => {
    const filtered = search.trim() ? data.teachers.filter((t) => matchesName(t.fullName, search)) : data.teachers;
    return sortTeachers(filtered, sort);
  }, [data.teachers, search, sort]);

  const board = useMemo<BoardItem[]>(
    () =>
      rows.map((t) => ({
        id: t.id,
        name: t.fullName,
        value: presenceRate(t),
        unit: '%',
        detail: [
          t.position,
          `${t.periodPresentDays} kun keldi`,
          t.periodLateDays > 0 ? `${t.periodLateDays} kech` : null,
          t.periodAbsentDays > 0 ? `${t.periodAbsentDays} kelmagan` : null,
          hasPeriodLessons ? `darsga o'z vaqtida ${formatPercent(t.onTimeRate)}` : null,
        ]
          .filter(Boolean)
          .join(' · '),
        headcount: null,
      })),
    [rows, hasPeriodLessons],
  );
  const sortedBoard = useMemo(() => (sort === 'name' ? board : worstFirst(board)), [board, sort]);

  const columns: DataTableColumn<KafedraTeacher>[] = [
    {
      key: 'name',
      header: "O'qituvchi",
      cell: (t) => (
        <div className="flex min-w-0 items-center gap-2">
          <Avatar name={t.fullName} src={t.photoUrl} size="sm" />
          <div className="min-w-0">
            <Link
              to={withDate(situationPaths.person(t.id))}
              onClick={(e) => e.stopPropagation()}
              title={t.fullName}
              className="block truncate text-[13px] font-medium text-fg hover:text-primary hover:underline"
            >
              {t.fullName}
            </Link>
            <p className="intel-micro truncate" title={t.position}>
              {t.position}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      header: data.isToday ? 'Bugun' : 'Shu kuni',
      cell: (t) => <StatusBadge status={t.status === 'malumot_yoq' ? 'nomalum' : t.status} time={t.checkIn} />,
    },
    ...(hasTodayLessons
      ? [{ key: 'lessons', header: 'Darslar', cell: (t: KafedraTeacher) => <TodayLessons t={t} /> }]
      : []),

    // Dars jadvali bo'lmasa bu ustun har satrda bo'sh halqa va "0 dars"
    // ko'rsatardi — ma'nosiz. Jadval paydo bo'lishi bilan ustun qaytadi.
    ...(hasPeriodLessons
      ? [
          {
            key: 'onTime',
            header: "Darsga o'z vaqtida",
            align: 'right' as const,
            width: '11rem',
            sortValue: (t: KafedraTeacher) => t.onTimeRate,
            cell: (t: KafedraTeacher) => (
              <span className="flex flex-col items-end gap-0.5">
                <RateCell value={t.onTimeRate} note="dars yo'q" />
                <span className="intel-micro">
                  {t.periodLessons} dars
                  {t.periodLate > 0 && ` · ${t.periodLate} kech`}
                  {t.periodMissed > 0 && ` · ${t.periodMissed} yo'q`}
                </span>
              </span>
            ),
          },
        ]
      : []),
    {
      key: 'days',
      header: 'Kelgan kunlari',
      align: 'right',
      width: '11rem',
      hideOnMobile: true,
      sortValue: (t) => presenceRate(t),
      cell: (t) => (
        <span className="flex flex-col items-end gap-0.5">
          <RateCell value={presenceRate(t)} note="yozuv yo'q" />
          <span className="intel-micro">
            {t.periodPresentDays} kun
            {t.periodLateDays > 0 && ` · ${t.periodLateDays} kech`}
            {t.periodAbsentDays > 0 && ` · ${t.periodAbsentDays} yo'q`}
          </span>
        </span>
      ),
    },
  ];

  return (
    <>
      {data.teachers.length === 0 ? (
        <EmptyState
          icon={Users}
          title="Bu bo'linmada xodim yo'q"
          description="Xodim «Shaxslar reestri» bo'limida biriktiriladi."
        />
      ) : rows.length === 0 ? (
        <EmptyState icon={Users} compact title="Hech kim topilmadi" />
      ) : view === 'board' ? (
        <IntelPanel title="Xodimlar" code={`${rows.length} ta`}>
          <StatusBoard
            items={sortedBoard}
            emptyText="Bu davrda yozuv yo'q"
            onOpen={(id) => setSelected(rows.find((t) => t.id === id) ?? null)}
          />
          <RagLegend />
        </IntelPanel>
      ) : (
        <IntelPanel title="Xodimlar" code={`${rows.length} qator`}>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(t) => t.id}
            onRowClick={setSelected}
            selectedKey={selected?.id ?? null}
            manualSort
            rowRag={(t) => {
              const value = presenceRate(t);
              return value === null ? 'yoq' : rag(value, RATE_RAG);
            }}
            ragHeader="Davr"
            ariaLabel="Kafedra o'qituvchilari"
            dense
          />
        </IntelPanel>
      )}

      <TeacherDayDrawer
        person={selected ? { id: selected.id, fullName: selected.fullName, photoUrl: selected.photoUrl, subtitle: selected.position } : null}
        date={date}
        onClose={() => setSelected(null)}
      >
        {/* "To'liq profil" tugmasi olib tashlandi: Drawer pastida allaqachon
            "Profilni ochish" bor edi va u ko'rilayotgan sanani saqlardi, bu
            esa yo'q — bitta odamga ikki xil havola chiqardi. */}
        {selected && (
          <div className="border border-border bg-surface">
            <div className="flex items-center justify-between gap-3 border-b border-border bg-surface-2 px-3 py-2">
              <div className="min-w-0">
                <MicroLabel>Davr</MicroLabel>
                <p className="intel-code text-[13px] font-semibold text-fg">{formatUzRange(data.period.dateFrom, data.period.dateTo)}</p>
              </div>
              <span className="flex items-center gap-2">
                <StatusMark status={selected.status === 'malumot_yoq' ? 'malumot_yoq' : selected.status} label={data.isToday ? 'Bugun' : data.date} />
                <RateCell value={presenceRate(selected)} note="yozuv yo'q" />
              </span>
            </div>
            <div className={cn('p-3', hasPeriodLessons ? undefined : 'pb-3')}>
              <KeyValue
                layout="stacked"
                columns={4}
                items={[
                  ...(hasPeriodLessons
                    ? [
                        { label: 'Darslar', value: selected.periodLessons },
                        { label: "O'z vaqtida", value: selected.periodOnTime },
                        { label: 'Kech keldi', value: selected.periodLate },
                        { label: 'Kelmagan', value: selected.periodMissed },
                      ]
                    : []),
                  { label: 'Kelgan', value: selected.periodPresentDays },
                  { label: 'Kech kelgan', value: selected.periodLateDays },
                  { label: 'Kelmagan', value: selected.periodAbsentDays },
                ]}
              />
            </div>
          </div>
        )}
      </TeacherDayDrawer>
    </>
  );
}

function LessonsSection({ rows, total, loading, error, onRetry }: { rows: Lesson[]; total: number; loading: boolean; error: string | null; onRetry: () => void }) {
  const [selected, setSelected] = useState<Lesson | null>(null);
  return (
    <IntelPanel
      title="Darslar"
      // Tab hisoblagichi serverdagi `total` ni ko'rsatadi, jadvalga esa bir
      // sahifa (500 ta) tushadi — kod ikkalasini ham aytadi.
      code={`${rows.length} / ${total}`}
    >
      <LessonsTable
        rows={rows}
        loading={loading}
        error={error}
        onRetry={onRetry}
        onRowClick={setSelected}
        selectedId={selected?.id ?? null}
        showState
        emptyTitle="Darslar yo'q"
        emptyDescription="Dars jadvali hali yuklanmagan."
      />
      <LessonDrawer lesson={selected} onClose={() => setSelected(null)} />
    </IntelPanel>
  );
}
