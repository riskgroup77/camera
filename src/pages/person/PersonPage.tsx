import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { PersonRouteDrawer } from './PersonRouteDrawer';
import { ArrowLeft, CalendarDays, FileVideo, Footprints, GraduationCap, MapPin, RefreshCw, Route } from 'lucide-react';
import {
  Badge,
  Button,
  ButtonLink,
  CodeText,
  DataTable,
  DateRangePicker,
  EmptyState,
  ErrorState,
  IconButton,
  IntelPanel,
  MicroLabel,
  Page,
  Skeleton,
  SkeletonTiles,
  StatusLamp,
  Tabs,
  Toolbar,
  cn,
  focusRing,
  formatNumber,
  formatPercent,
  formatUzDate,
  formatUzRange,
  isIsoDate,
  rangeForPreset,
  detectPreset,
  useUrlTab,
  type DataTableColumn,
  type DateRangeValue,
  type TabItem,
} from '../../ui';
import { api, isAbortError } from '../../lib/apiClient';
import { getAttendancePolicy } from '../../lib/attendancePolicyApi';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { useLiveAttendance, type LiveAttendanceMessage } from '../../lib/realtime';
import { getPerson, situationPaths, type Lesson, type PersonLesson, type PersonProfile } from '../../lib/situationApi';
import { DEFAULT_WORKING_WEEKDAYS, buildMonthGrid, monthOf, type CalendarCell } from '../../lib/attendanceCalendar';
import {
  lateAfterMinutes,
  LESSON_ATTENDANCE_META,
  arrivalSeries,
  lessonTime,
  monthsInRange,
  personKpis,
  previousRange,
  statusMeta,
  visitsByDate,
  weekdayPattern,
} from '../../lib/studentAttendance';
import { formatMinutes } from '../../lib/uzDate';
import { useViewDate } from '../../lib/viewDate';
import type { AttendanceDay, AttendanceSummary } from '../../types';
import DayDrawer from '../../components/attendance/DayDrawer';
import MonthTrend from '../../components/attendance/MonthTrend';
import { CalendarLegend, MonthCalendar } from '../../components/attendance/MonthCalendar';
import { LessonDrawer, TeacherPunctuality } from '../../components/students/LessonViews';
import { PersonPhoto } from '../../components/students/PersonPhoto';
import { ArrivalTimeChart } from '../../components/students/TrendCharts';
import { errorText, useAsyncData } from '../../components/students/useAsyncData';
import { GroupEnrollDrawer, type EnrollDrawerTarget } from '../../components/students/GroupEnrollDrawer';
import { EnrollCta, StaffKpis, WeekdayPatternCard } from '../../components/attendance/PersonInsights';
import { KpiReadout, StaleNote, StatusMark } from '../../components/attendance/readout';
import PersonCriteriaTab from '../../components/videoAnalysis/PersonCriteriaTab';

type TabId = 'davomat' | 'darslar' | 'harakatlar' | 'kriteriyalar';
const PRESETS = ['week', 'month', 'last30', 'lastMonth'] as const;
const MAX_CALENDAR_MONTHS = 6;
const MONTH_TTL_MS = 60_000;
/** Server `recentVisits` ni shuncha yozuv bilan cheklaydi. */
const RECENT_VISITS_LIMIT = 20;

// Oylik yozuvlar keshi (odam+oy) — sahifadan chiqib qaytganda darhol chiziladi.
const monthCache = new Map<string, { at: number; days: AttendanceDay[] }>();
const cacheKey = (personId: string, month: string) => `${personId}:${month}`;

/** /api/attendance/{id}?month= — ko'rinayotgan oylar (erta ketish, yozuv borligi). */
function useMonthRecords(personId: string, months: string[]) {
  const [state, setState] = useState<Record<string, AttendanceDay[]>>({});
  // Oy so'rovi yiqilsa kalendar avval abadiy "yuklanmoqda" bo'lib turardi:
  // xato `.catch(() => null)` da yutilardi, foydalanuvchi na sababni ko'rar,
  // na qayta urinish tugmasini topardi.
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const monthsKey = months.join(',');

  useEffect(() => {
    const list = monthsKey ? monthsKey.split(',') : [];
    const fresh: Record<string, AttendanceDay[]> = {};
    const missing: string[] = [];
    for (const m of list) {
      const hit = monthCache.get(cacheKey(personId, m));
      if (hit) fresh[m] = hit.days;
      if (!hit || Date.now() - hit.at > MONTH_TTL_MS) missing.push(m);
    }
    setState(fresh);
    setError(null);
    if (!missing.length) return;
    const controller = new AbortController();
    const failed: string[] = [];
    Promise.all(
      missing.map((m) =>
        api
          .get<AttendanceDay[]>(`/api/attendance/${encodeURIComponent(personId)}?month=${m}`, undefined, { signal: controller.signal })
          .then((days) => {
            monthCache.set(cacheKey(personId, m), { at: Date.now(), days });
            return [m, days] as const;
          })
          .catch((err: unknown) => {
            if (!isAbortError(err)) failed.push(errorText(err));
            return null;
          }),
      ),
    ).then((results) => {
      if (controller.signal.aborted) return;
      setState((prev) => {
        const next = { ...prev };
        for (const r of results) if (r) next[r[0]] = r[1];
        return next;
      });
      setError(failed[0] ?? null);
    });
    return () => controller.abort();
  }, [personId, monthsKey, version]);

  const invalidate = useCallback(
    (month?: string) => {
      if (month) monthCache.delete(cacheKey(personId, month));
      else for (const key of [...monthCache.keys()]) if (key.startsWith(`${personId}:`)) monthCache.delete(key);
      setVersion((v) => v + 1);
    },
    [personId],
  );
  const apply = useCallback(
    (date: string, update: (days: AttendanceDay[]) => AttendanceDay[]) => {
      const m = monthOf(date);
      const base = monthCache.get(cacheKey(personId, m))?.days ?? [];
      const days = update(base).sort((a, b) => a.date.localeCompare(b.date));
      monthCache.set(cacheKey(personId, m), { at: Date.now(), days });
      setState((prev) => ({ ...prev, [m]: days }));
    },
    [personId],
  );
  return { records: state, error, invalidate, apply, reload: invalidate };
}

function readRange(params: URLSearchParams, today: string): DateRangeValue {
  const from = params.get('dan');
  const to = params.get('gacha');
  if (isIsoDate(from) && isIsoDate(to) && from <= to) {
    const clampedTo = to > today ? today : to;
    // `gacha` bugundan keyin bo'lsa u bugungi kunga qisqartiriladi. Ilgari
    // BUTUN oraliq kelajakda bo'lganda (masalan ?dan=2026-10-01&gacha=
    // 2026-10-31) qisqartirishdan keyin from > to bo'lib qolardi va serverga
    // teskari oraliq ketardi. Bunday oraliqda ko'rsatadigan hech narsa yo'q —
    // standart oyga qaytamiz.
    if (from > clampedTo) return rangeForPreset('month', today);
    return { from, to: clampedTo, preset: detectPreset({ from, to: clampedTo }, PRESETS, today) };
  }
  return rangeForPreset('month', today);
}

/** Hujjatdagi bitta "maydon": ustida kichik bosh harfli yorliq, ostida
 *  qiymat. Qiymat odam nomi yoki joy nomi bo'lishi mumkin — u proza,
 *  shuning uchun sans shriftda qoladi. */
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt>
        <MicroLabel>{label}</MicroLabel>
      </dt>
      <dd className="mt-0.5 truncate text-[13px] font-medium text-fg">{children}</dd>
    </div>
  );
}

const linkClass = cn('rounded text-primary hover:underline', focusRing);

/** Shaxs profili (talaba yoki o'qituvchi/xodim): surat, bugungi holat,
 *  davr bo'yicha kalendar, darslar va kameralardagi harakatlar. */
export default function PersonPage() {
  const { personId = '' } = useParams();
  const { today, withDate } = useViewDate();
  const { role } = useAuth();
  const { can } = usePermissions();
  const canEdit = can('manageAttendance', role);
  // Kameralar bo'yicha kunlik yo'l — Shaxs qidirish bilan bir xil ruxsat.
  const canTrack = can('viewLive', role);
  const [routeOpen, setRouteOpen] = useState(false);
  const [params, setParams] = useSearchParams();
  const range = readRange(params, today);

  function setRange(next: DateRangeValue) {
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        const def = rangeForPreset('month', today);
        if (next.from === def.from && next.to === def.to) {
          p.delete('dan');
          p.delete('gacha');
        } else if (next.from && next.to && next.from <= next.to) {
          p.set('dan', next.from);
          p.set('gacha', next.to);
        }
        return p;
      },
      { replace: true },
    );
  }

  const profile = useAsyncData<PersonProfile>(
    `${personId}|${range.from}|${range.to}`,
    (signal) => getPerson(personId, { from: range.from, to: range.to }, { signal }),
    { identity: personId },
  );
  const summary = useAsyncData<AttendanceSummary>(
    `sum|${personId}`,
    (signal) => api.get<AttendanceSummary>(`/api/attendance/${encodeURIComponent(personId)}/summary?months=6`, undefined, { signal }),
    { identity: personId },
  );
  const data = profile.data;
  const person = data?.person;
  const isStaff = person?.type === 'xodim';
  // Kechikish chegarasi — Sozlamalar → Ish vaqti (talaba/xodim alohida),
  // server kech_keldi ni shu qoida bilan yozadi. Ilgari 09:00 qotirilgan edi.
  const policy = useAsyncData('attendance-policy', (signal) => getAttendancePolicy(null, { signal }));
  const lateCutoff = lateAfterMinutes(
    person?.type === 'talaba' ? policy.data?.studentLateAfter : policy.data?.staffLateAfter,
  );
  const lateLabel = `${String(Math.floor(lateCutoff / 60)).padStart(2, '0')}:${String(lateCutoff % 60).padStart(2, '0')}`;
  // Qoida hali kelmagan (yoki so'rov yiqilgan) bo'lsa `lateCutoff` — koddagi
  // zaxira qiymat. Uni ANIQ soat sifatida yozib qo'yish yolg'on bo'lardi:
  // izohlar faqat haqiqiy qoida kelganda soatni nomlaydi.
  const cutoffKnown = policy.data != null;
  // Xodim: oldingi, xuddi shu uzunlikdagi davr — KPI o'zgarishlari uchun.
  const prevRange = previousRange(range.from, range.to);
  const previous = useAsyncData<PersonProfile>(
    isStaff ? `prev|${personId}|${prevRange.from}|${prevRange.to}` : null,
    (signal) => getPerson(personId, prevRange, { signal }),
    { identity: personId },
  );
  const kpis = useMemo(() => (data ? personKpis(data.calendar) : null), [data]);
  const prevKpis = useMemo(() => {
    if (!previous.data) return null;
    const k = personKpis(previous.data.calendar);
    // Oldingi davrda yozuv yo'q — taqqoslash ma'nosiz ("+14" chalg'itadi).
    return k.presentDays + k.absentDays > 0 ? k : null;
  }, [previous.data]);
  const weekdays = useMemo(() => (data ? weekdayPattern(data.calendar) : []), [data]);
  const [enrollTarget, setEnrollTarget] = useState<EnrollDrawerTarget | null>(null);
  const workingWeekdays = summary.data?.workingWeekdays ?? DEFAULT_WORKING_WEEKDAYS;

  const currentMonth = monthOf(today);
  const calendarMonths = useMemo(() => monthsInRange(range.from, range.to, MAX_CALENDAR_MONTHS).reverse(), [range.from, range.to]);
  const neededMonths = useMemo(() => [...new Set([currentMonth, ...calendarMonths])], [currentMonth, calendarMonths]);
  const months = useMonthRecords(personId, neededMonths);

  const cellsByMonth = useMemo(() => {
    const out: Record<string, CalendarCell[] | null> = {};
    for (const m of neededMonths) out[m] = months.records[m] ? buildMonthGrid(months.records[m], m, today, workingWeekdays) : null;
    return out;
  }, [neededMonths, months.records, today, workingWeekdays]);

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  useEffect(() => {
    setSelectedDate(null);
    setLesson(null);
  }, [personId]);

  // Jonli: shu odam kamerada tanilsa — bugungi holat va kalendar yangilanadi.
  const reloadProfile = profile.reload;
  const reloadSummary = summary.reload;
  const invalidate = months.invalidate;
  useLiveAttendance(
    useCallback(
      (m: LiveAttendanceMessage) => {
        if (m.personId !== personId) return;
        invalidate(monthOf(m.date));
        reloadProfile();
        reloadSummary();
      },
      [personId, invalidate, reloadProfile, reloadSummary],
    ),
  );

  const todayCell = cellsByMonth[currentMonth]?.find((c) => c.date === today) ?? null;
  // Joriy oy yozuvlari hali kelmaganda "Bugun" plitkasi «Kutilmoqda» deb
  // turib, keyin «Keldi»ga sakrardi — yolg'on holat. Ma'lumot kelguncha
  // «Noma'lum» (StatusBadge uni neytral ko'rsatadi).
  const todayLoaded = cellsByMonth[currentMonth] != null;
  const todayStatus =
    todayCell && todayCell.isRecord
      ? todayCell.status
      : todayLoaded && person?.biometricsStatus === 'tasdiqlangan'
        ? 'kutilmoqda'
        : 'nomalum';

  // Kun oynasidagi «oldingi/keyingi» faqat KO'RINAYOTGAN oylar bo'ylab
  // yursin. Ilgari bu yerga joriy oy ham qo'shilardi (u "Bugun" plitkasi
  // uchun yuklanadi), shuning uchun avgustni ko'rib turgan odam «keyingi»
  // bilan kalendarda umuman yo'q sentyabr kuniga tushib qolardi.
  const allCells = useMemo(
    () => calendarMonths.flatMap((m) => cellsByMonth[m] ?? []).sort((a, b) => a.date.localeCompare(b.date)),
    [calendarMonths, cellsByMonth],
  );
  const selectedIndex = selectedDate ? allCells.findIndex((c) => c.date === selectedDate) : -1;
  const selectedCell: CalendarCell | null =
    selectedIndex >= 0
      ? allCells[selectedIndex]
      : selectedDate
        ? {
            date: selectedDate,
            day: Number(selectedDate.slice(8)),
            status: 'malumot_yoq',
            checkIn: null,
            checkOut: null,
            earlyLeave: false,
            isRecord: false,
            isToday: selectedDate === today,
            isWorkingDay: true,
            presenceMinutes: null,
          }
        : null;
  const prevCell = selectedIndex > 0 ? allCells[selectedIndex - 1] : null;
  const nextCell = selectedIndex >= 0 && selectedIndex < allCells.length - 1 && allCells[selectedIndex + 1].status !== 'kelajak' ? allCells[selectedIndex + 1] : null;

  const visitsCapped = (data?.recentVisits.length ?? 0) >= RECENT_VISITS_LIMIT;
  const tabs: TabItem<TabId>[] = [
    { id: 'davomat', label: 'Davomat', icon: CalendarDays },
    // Dars jadvali yo'q shaxsda tab ham yo'q — doimo bo'sh jadval o'rniga.
    ...(data && data.lessons.length > 0
      ? [{ id: 'darslar' as const, label: 'Darslar', icon: GraduationCap, count: data.lessons.length }]
      : []),
    // Server tashriflarni 20 ta bilan cheklaydi (situation.py: .limit(20)).
    // Shu sababli "20" — davrdagi tashriflar soni EMAS, faqat chegara: uni
    // tab hisoblagichida ko'rsatish "bu davrda 20 marta ko'ringan" degan
    // yolg'on ma'no berardi.
    { id: 'harakatlar', label: "Qayerda ko'ringan", icon: Footprints, count: visitsCapped ? null : (data?.recentVisits.length ?? null) },
    // Kunlik video tahlil: xalat, diqqat, chekish, o'qituvchi faolligi.
    { id: 'kriteriyalar', label: 'Kriteriyalar', icon: FileVideo },
  ];
  const [tab, setTab] = useUrlTab(tabs, { defaultTab: 'davomat' });

  const isStudent = person?.type === 'talaba';
  const crumbs = person
    ? isStudent
      ? [
          { label: 'Talabalar', to: withDate(situationPaths.faculties) },
          ...(person.group ? [{ label: person.group, to: withDate(situationPaths.group(person.group)) }] : []),
          { label: person.fullName },
        ]
      : [
          { label: "O'qituvchilar", to: withDate('/oqituvchilar') },
          ...(person.departmentId && person.department ? [{ label: person.department, to: withDate(situationPaths.kafedra(person.departmentId)) }] : []),
          { label: person.fullName },
        ]
    : [{ label: 'Shaxs' }];


  function afterEdit(date: string, update: (days: AttendanceDay[]) => AttendanceDay[]) {
    months.apply(date, update);
    profile.reload();
    summary.reload();
  }

  return (
    <Page
      title={person?.fullName ?? 'Shaxs profili'}
      subtitle={person ? (isStudent ? person.group || 'Talaba' : person.position || person.unit || 'Xodim') : undefined}
      breadcrumbs={crumbs}
      actions={
        <>
          {person && canTrack && (
            <Button icon={Route} variant="secondary" onClick={() => setRouteOpen(true)}>
              Yo‘li
            </Button>
          )}
          <IconButton icon={RefreshCw} label="Yangilash" variant="secondary" onClick={() => { profile.reload(); summary.reload(); previous.reload(); months.invalidate(); }} loading={profile.refreshing} />
        </>
      }
    >
      {profile.loading ? (
        <>
          <Skeleton className="h-40" />
          <SkeletonTiles count={5} className="xl:grid-cols-5" />
        </>
      ) : profile.error && !data ? (
        <div className="border border-border bg-surface">
          <ErrorState variant="block" title={/topilmadi/i.test(profile.error) ? 'Shaxs topilmadi' : undefined} message={profile.error} onRetry={profile.reload} />
          <div className="flex justify-center pb-8">
            <ButtonLink to={withDate(situationPaths.faculties)} icon={ArrowLeft} variant="ghost">
              Orqaga
            </ButtonLink>
          </div>
        </div>
      ) : data && person ? (
        <div className="flex min-w-0 flex-col gap-3">
          {/* Shaxsiyat bloki — surat, uchta fakt, bugungi holat. */}
          <IntelPanel
            title="Shaxs"
            right={person.active ? undefined : <StatusLamp status="alert" label="Faol emas" />}
          >
            <div className="flex flex-col gap-4 p-3 md:flex-row md:items-start">
              <PersonPhoto
                name={person.fullName}
                src={person.photoUrl}
                tone={statusMeta(todayStatus === 'nomalum' ? 'malumot_yoq' : todayStatus).tone}
                className="h-36 w-28 self-start"
                textClassName="text-4xl"
              />
              <div className="min-w-0 flex-1">
                {/* Ism sahifa sarlavhasida turibdi — bu yerda faqat uchta
                    fakt: qayerda, qaysi kursda/lavozimda va bugun qanday. */}
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 lg:grid-cols-3">
                  {isStudent ? (
                    <>
                      <Fact label="Fakultet">
                        <Link to={withDate(situationPaths.faculty(person.facultyId))} className={linkClass}>
                          {person.faculty ?? 'Fakultetsiz'}
                        </Link>
                      </Fact>
                      <Fact label="Guruh">
                        {person.group ? (
                          <Link to={withDate(situationPaths.group(person.group))} className={linkClass}>
                            {person.group}
                          </Link>
                        ) : (
                          'Biriktirilmagan'
                        )}
                      </Fact>
                    </>
                  ) : (
                    <>
                      <Fact label="Bo'linma">
                        {person.departmentId ? (
                          <Link to={withDate(situationPaths.kafedra(person.departmentId))} className={linkClass}>
                            {person.department}
                          </Link>
                        ) : (
                          'Biriktirilmagan'
                        )}
                      </Fact>
                      <Fact label="Lavozim">{person.position || person.unit || "Ko'rsatilmagan"}</Fact>
                    </>
                  )}
                  <Fact label="Yuz">
                    {person.biometricsStatus !== 'tasdiqlangan' ? (
                      <span className="text-warning">Ro‘yxatdan o‘tmagan — kameralar tanimaydi</span>
                    ) : (person.photoAngles ?? 0) >= 3 ? (
                      'Tasdiqlangan · 3 tomon'
                    ) : (
                      <span className="text-warning">{`Tasdiqlangan · ${person.photoAngles ?? 0}/3 tomon — qayta o‘tishi kerak`}</span>
                    )}
                  </Fact>
                  <Fact label="Bugun">
                    <span className="flex items-center gap-2">
                      <StatusMark
                        status={todayStatus === 'nomalum' ? 'malumot_yoq' : todayStatus}
                        label={statusMeta(todayStatus === 'nomalum' ? 'malumot_yoq' : todayStatus).label}
                        showLabel
                      />
                      {todayCell?.checkIn && <CodeText className="text-[12px] text-fg">{todayCell.checkIn}</CodeText>}
                    </span>
                  </Fact>
                </dl>
              </div>
            </div>
          </IntelPanel>

          {person.biometricsStatus !== 'tasdiqlangan' && (
            <EnrollCta
              student={isStudent}
              group={person.group}
              pending={person.biometricsStatus === 'kutilmoqda'}
              onOpenGroup={person.group ? () => setEnrollTarget({ name: person.group!, faculty: person.faculty }) : undefined}
              registryLink={`/reestr?search=${encodeURIComponent(person.fullName)}`}
            />
          )}

          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          <Toolbar>
            <DateRangePicker value={range} onChange={setRange} presets={PRESETS} />
          </Toolbar>
          {profile.error && <StaleNote message={profile.error} onRetry={profile.reload} />}

          {tab === 'davomat' && (
            <>
              {/* 3. Ko'rsatkichlar lentasi. */}
              <IntelPanel title="Davr ko'rsatkichlari">
                {isStaff && kpis ? (
                  <StaffKpis current={kpis} previous={prevKpis} lateCutoff={lateCutoff} />
                ) : (
                  // Foiz = kelgan / (kelgan + kelmagan); izoh ham AYNAN shu ikki
                  // sondan yoziladi. Ilgari u butun davrdagi kunlar sonini (dam
                  // olish kunlari bilan) "ish kuni" deb ko'rsatardi.
                  <KpiReadout
                    className="lg:grid-cols-4"
                    items={[
                      {
                        label: 'Kelgan kunlari ulushi',
                        value: formatPercent(data.totals.rate, 1),
                        rate: data.totals.rate,
                        hint: `Yozuv bor ${data.totals.present + data.totals.absent} kundan ${data.totals.present} tasida kelgan`,
                      },
                      {
                        label: "O'z vaqtida kelgan",
                        value: `${data.totals.present - data.totals.late} kun`,
                        hint: cutoffKnown ? `Soat ${lateLabel} gacha` : undefined,
                      },
                      { label: 'Kech kelgan', value: `${data.totals.late} kun` },
                      { label: 'Kelmagan', value: `${data.totals.absent} kun` },
                    ]}
                  />
                )}
              </IntelPanel>

              {/* 4. Kalendar — aniq to'r, kaliti bilan. */}
              <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
                <IntelPanel title="Kunlar kalendari" code={formatUzRange(data.dateFrom, data.dateTo)}>
                  <div className={cn('grid gap-3 p-3', calendarMonths.length > 1 && '2xl:grid-cols-2')}>
                    {calendarMonths.map((m) => (
                      <div key={m} className="border border-border">
                        <MonthCalendar
                          month={m}
                          cells={cellsByMonth[m] ?? null}
                          workingWeekdays={workingWeekdays}
                          selectedDate={selectedDate}
                          onOpen={setSelectedDate}
                          range={range}
                        />
                      </div>
                    ))}
                  </div>
                  {/* Oy yozuvlari kelmasa kalendar bo'sh kataklar bilan
                      qolib ketmasin — sabab va qayta urinish ko'rsatiladi. */}
                  {months.error && <ErrorState className="mx-3 mb-3" title="Kalendar yuklanmadi" message={months.error} onRetry={() => months.reload()} />}
                  <CalendarLegend className="border-t border-border" />
                </IntelPanel>

                <div className="flex min-w-0 flex-col gap-3">
                  {summary.data ? (
                    <MonthTrend
                      months={summary.data.months}
                      activeMonth={calendarMonths.length === 1 ? calendarMonths[0] : null}
                      onPick={(m) => {
                        const [y, mo] = m.split('-').map(Number);
                        const last = new Date(Date.UTC(y, mo, 0)).getUTCDate();
                        const to = `${m}-${String(last).padStart(2, '0')}`;
                        setRange({ preset: 'custom', from: `${m}-01`, to: to > today ? today : to });
                      }}
                    />
                  ) : summary.error ? (
                    <ErrorState message={summary.error} onRetry={summary.reload} />
                  ) : (
                    <Skeleton className="h-72" />
                  )}
                  {isStaff && <WeekdayPatternCard rows={weekdays} lateCutoff={lateCutoff} />}
                  <IntelPanel title="Kelish vaqti" right={cutoffKnown ? <MicroLabel>chegara {lateLabel}</MicroLabel> : undefined} bodyClassName="p-3">
                    {data.calendar.some((d) => d.checkIn) ? (
                      <ArrivalTimeChart
                        points={arrivalSeries(data.calendar)}
                        threshold={lateCutoff}
                        average={isStaff ? (kpis?.avgArrivalMinutes ?? null) : null}
                        height={isStaff ? 240 : undefined}
                      />
                    ) : (
                      <EmptyState compact bordered={false} title="Kelish vaqti qayd etilmagan" />
                    )}
                  </IntelPanel>
                </div>
              </div>
            </>
          )}

          {tab === 'kriteriyalar' && <PersonCriteriaTab personId={personId} isStudent={isStudent} />}

          {tab === 'darslar' && (
            <IntelPanel title="Darslar" code={`${data.lessons.length} ta`}>
              <LessonsTab lessons={data.lessons} isStudent={isStudent} onOpen={setLesson} withDate={withDate} />
            </IntelPanel>
          )}

          {tab === 'harakatlar' &&
            (data.recentVisits.length === 0 ? (
              <EmptyState
                icon={Footprints}
                title="Kamerada ko'rinmagan"
                description={person?.biometricsStatus === 'tasdiqlangan' ? undefined : "Yuzi ro'yxatdan o'tmagan."}
              />
            ) : (
              // Kod "so'nggi 20" deydi: bu davrdagi tashrif soni emas, server
              // chegarasi — boshqacha yozilsa yolg'on son bo'lardi.
              <IntelPanel
                title="Qayerda ko'ringan"
                code={visitsCapped ? `so'nggi ${RECENT_VISITS_LIMIT}` : `${data.recentVisits.length} ta`}
              >
                <div className="flex flex-col">
                  {visitsByDate(data.recentVisits).map((day) => (
                    <section key={day.date}>
                      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border-strong bg-surface-2 px-3 py-1">
                        <CodeText className="text-[12px] font-semibold text-fg">{day.date}</CodeText>
                        <h3 className="intel-micro !text-fg">{formatUzDate(day.date, { weekday: true })}</h3>
                        <span className="intel-code text-[11px] text-muted">
                          {day.visits.length} marta · {formatMinutes(day.minutes)}
                        </span>
                        <Button size="sm" variant="ghost" icon={CalendarDays} className="ms-auto" onClick={() => setSelectedDate(day.date)}>
                          Ochish
                        </Button>
                      </header>
                      <ol className="divide-y divide-border">
                        {day.visits.map((v) => (
                          <li key={v.id} className="flex flex-wrap items-center gap-x-4 gap-y-0.5 px-3 py-1 text-[13px]">
                            <CodeText className="w-28 shrink-0 font-semibold text-fg">
                              {v.firstSeen === v.lastSeen ? v.firstSeen : `${v.firstSeen}–${v.lastSeen}`}
                            </CodeText>
                            <span className="inline-flex min-w-0 flex-1 items-center gap-1.5 text-fg">
                              <MapPin size={13} className="shrink-0 text-subtle" aria-hidden="true" />
                              <span className="truncate">{[v.camera, v.zone, v.building].filter(Boolean).join(' · ')}</span>
                            </span>
                            <CodeText className="text-[12px] text-muted">
                              {formatMinutes(v.durationMinutes)} · {formatNumber(v.sightings)} marta
                            </CodeText>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              </IntelPanel>
            ))}

        </div>
      ) : null}

      <DayDrawer
        open={selectedCell !== null}
        personId={personId}
        personName={person?.fullName ?? ''}
        cell={selectedCell}
        canEdit={canEdit}
        onClose={() => setSelectedDate(null)}
        onPrev={prevCell ? () => setSelectedDate(prevCell.date) : undefined}
        onNext={nextCell ? () => setSelectedDate(nextCell.date) : undefined}
        onSaved={(day) => afterEdit(day.date, (days) => [...days.filter((d) => d.date !== day.date), day])}
        onDeleted={(date) => afterEdit(date, (days) => days.filter((d) => d.date !== date))}
      />
      <LessonDrawer lesson={lesson} withDate={withDate} showGroupLink onClose={() => setLesson(null)} />
      <GroupEnrollDrawer target={enrollTarget} onClose={() => setEnrollTarget(null)} withDate={withDate} />
      <PersonRouteDrawer
        target={routeOpen && person ? { id: person.id, fullName: person.fullName } : null}
        onClose={() => setRouteOpen(false)}
      />
    </Page>
  );
}

function LessonsTab({
  lessons,
  isStudent,
  onOpen,
  withDate,
}: {
  lessons: PersonLesson[];
  isStudent: boolean;
  onOpen: (lesson: Lesson) => void;
  withDate: (path: string) => string;
}) {
  const columns: DataTableColumn<PersonLesson>[] = [
    { key: 'date', header: 'Sana', cell: (l) => formatUzDate(l.date, { weekday: false, year: false }), sortValue: (l) => `${l.date} ${l.startsAt ?? ''}`, width: '8rem' },
    { key: 'time', header: 'Vaqt', cell: (l) => <span className="tabular-nums">{lessonTime(l)}</span>, hideOnMobile: true },
    { key: 'subject', header: 'Fan', cell: (l) => <span className="font-medium text-fg">{l.subject}</span>, sortValue: (l) => l.subject },
    isStudent
      ? { key: 'teacher', header: "O'qituvchi", cell: (l) => l.teacher || '—', sortValue: (l) => l.teacher, hideOnMobile: true }
      : {
          key: 'group',
          header: 'Guruh',
          cell: (l) => (
            <Link to={withDate(situationPaths.group(l.groupName))} onClick={(e) => e.stopPropagation()} className={linkClass}>
              {l.groupName}
            </Link>
          ),
          sortValue: (l) => l.groupName,
        },
    { key: 'room', header: 'Xona', cell: (l) => l.room ?? '—', hideOnMobile: true },
    isStudent
      ? {
          key: 'own',
          header: 'Kirganmi',
          cell: (l) => {
            const meta = l.attendanceStatus ? LESSON_ATTENDANCE_META[l.attendanceStatus] : null;
            return meta ? (
              <Badge tone={meta.tone} dot>
                {meta.label}
                {l.firstSeen && <span className="ml-1 tabular-nums opacity-80">{l.firstSeen}</span>}
              </Badge>
            ) : (
              <Badge>{l.state === 'upcoming' ? 'Boshlanmagan' : 'Hisoblanmagan'}</Badge>
            );
          },
          sortValue: (l) => l.attendanceStatus,
        }
      : { key: 'punct', header: 'Kirgani', cell: (l) => <TeacherPunctuality lesson={l} />, sortValue: (l) => l.teacherStatus },
    {
      key: 'att',
      header: 'Talabalar',
      align: 'right',
      cell: (l) => (
        <span className="tabular-nums">
          {l.finalized ? l.present : l.seen}
          <span className="text-muted"> / {l.expected}</span>
        </span>
      ),
      hideOnMobile: isStudent,
    },
  ];
  return (
    <DataTable
      ariaLabel="Darslar"
      columns={columns}
      rows={lessons}
      rowKey={(l) => l.id}
      onRowClick={onOpen}
      rowTone={(l) => {
        if (isStudent) return l.attendanceStatus ? LESSON_ATTENDANCE_META[l.attendanceStatus].tone : null;
        return l.teacherStatus === 'kelmadi' ? 'danger' : l.teacherStatus === 'kechikdi' ? 'warning' : l.teacherStatus === 'oz_vaqtida' ? 'success' : null;
      }}
      dense
      emptyTitle="Dars yo'q"
      emptyDescription="Dars jadvali hali yuklanmagan."
    />
  );
}
