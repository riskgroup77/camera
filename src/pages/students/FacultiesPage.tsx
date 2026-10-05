import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, CalendarCheck, RefreshCw, ScanFace } from 'lucide-react';
import {
  Button,
  EmptyState,
  ErrorState,
  IconButton,
  IntelPanel,
  Page,
  SkeletonCards,
  SkeletonTiles,
  Toolbar,
  formatNumber,
  formatPercent,
  formatUzDate,
  useShell,
  useUrlTab,
  type TabItem,
} from '../../ui';
import { RagLegend, StatusBoard, type BoardItem } from '../../components/hisobot/board';
import { KpiReadout, StaleNote, worstFirst } from '../../components/attendance/readout';
import { getOverview, situationPaths, type Overview } from '../../lib/situationApi';
import { enrolledPct, hasAttendanceData } from '../../lib/studentAttendance';
import { useLiveAttendance, type LiveAttendanceMessage } from '../../lib/realtime';
import { useViewDate } from '../../lib/viewDate';
import { LiveArrivals, type ArrivalItem } from '../../components/attendance/LiveArrivals';
import { QuickSearch } from '../../components/students/QuickSearch';
import { WeakestGroups } from '../../components/students/WeakestGroups';
import { useAsyncData } from '../../components/students/useAsyncData';
import { EnrollmentCampaign } from '../../components/students/EnrollmentCampaign';

type ViewId = 'davomat' | 'yuz';
const VIEW_PARAM = 'korinish';

const REFRESH_MS = 60_000;
const FEED_SIZE = 10;

/** /talabalar — har bir fakultet bo'yicha talabalar davomati. Yuzlar hali kam bo'lsa
 *  (studentsDataAvailable=false) asosiy ko'rinish — "Yuz topshirish" kampaniyasi. */
export default function FacultiesPage() {
  const { date, today, isToday, withDate } = useViewDate();
  const { presentation } = useShell();
  const navigate = useNavigate();
  const overview = useAsyncData<Overview>(`ov|${date}`, (signal) => getOverview(date, { signal }), {
    refreshMs: isToday ? REFRESH_MS : undefined,
  });
  const data = overview.data;
  const [live, setLive] = useState<ArrivalItem[]>([]);
  useEffect(() => setLive([]), [date]);

  const reload = overview.reload;
  useLiveAttendance(
    useCallback(
      (m: LiveAttendanceMessage) => {
        if (m.personType !== 'talaba' || m.date !== date) return;
        setLive((prev) =>
          [{ personId: m.personId, fullName: m.fullName, unit: m.group, status: m.status, checkIn: m.checkIn }, ...prev.filter((p) => p.personId !== m.personId)].slice(0, FEED_SIZE),
        );
      },
      [date],
    ),
    isToday,
  );
  // Jonli xabarlar kelganda jami sonlar ham yangilansin (server keshi 15 s).
  // MUHIM: taymer har yangi xabarda qayta boshlanmaydi. Ilgari `live`
  // o'zgarishi taymerni nolga qaytarardi — ertalabki oqimda xabarlar 5 s dan
  // tez kelgani uchun jami sonlar umuman yangilanmay qolardi.
  const reloadTimer = useRef(0);
  useEffect(() => {
    if (!live.length || reloadTimer.current) return;
    // 30 s: ertalabki oqimda har ochiq varaq serverdan har 5 s da
    // umumiy agregatni so'ramasin (server keshi baribir 15 s).
    reloadTimer.current = window.setTimeout(() => {
      reloadTimer.current = 0;
      reload();
    }, 30_000);
  }, [live, reload]);
  useEffect(
    () => () => {
      if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
    },
    [],
  );

  const arrivals = useMemo<ArrivalItem[]>(() => {
    const initial = (data?.lastArrivals ?? [])
      .filter((a) => a.type === 'talaba')
      .map((a) => ({ personId: a.id, fullName: a.fullName, photoUrl: a.photoUrl, unit: a.unit, status: a.status, checkIn: a.time }));
    const seen = new Set(live.map((l) => l.personId));
    return [...live, ...initial.filter((a) => !seen.has(a.personId))].slice(0, FEED_SIZE);
  }, [data, live]);

  const s = data?.students;
  // Talabasi yo'q fakultet (HEMIS'da bor, lekin talaba biriktirilmagan)
  // taxtada joy egallab, "0 kishi" bilan chalg'itmasin — soni pastda aytiladi.
  const faculties = useMemo(() => data?.byFaculty.filter((f) => f.total > 0) ?? [], [data]);
  const emptyFaculties = useMemo(() => data?.byFaculty.filter((f) => f.total === 0 && f.id !== null).length ?? 0, [data]);
  const available = data ? data.studentsDataAvailable : true;
  const views: TabItem<ViewId>[] = [
    { id: 'davomat', label: 'Davomat', icon: CalendarCheck },
    { id: 'yuz', label: 'Yuz topshirish', icon: ScanFace },
  ];
  const defaultView: ViewId = available ? 'davomat' : 'yuz';
  const [view, setView] = useUrlTab(views, { param: VIEW_PARAM, defaultTab: defaultView });

  // Taxtadagi kataklar. Yuzi yetarli yig'ilmagan fakultetda foiz BOR, lekin
  // u guruhning kichik qismidan chiqqan — unga svetofor qo'yish yolg'on
  // hukm bo'lardi, shuning uchun qiymat "o'lchanmagan" deb uzatiladi va
  // sababi ikkinchi qatorda yoziladi.
  const board = useMemo<BoardItem[]>(
    () =>
      faculties.map((f) => {
        const measured = f.total > 0 && hasAttendanceData(f);
        return {
          id: f.id ?? 'none',
          name: f.name,
          value: measured ? f.rate : null,
          unit: '%',
          detail:
            f.total === 0
              ? "Talaba yo'q"
              : measured
                ? `${formatNumber(f.present)} / ${formatNumber(f.present + f.absent + f.notYet)} keldi`
                : `Yuzi ro'yxatda ${formatPercent(enrolledPct(f))}`,
          headcount: f.total,
        };
      }),
    [faculties],
  );
  const sortedBoard = useMemo(() => worstFirst(board), [board]);

  return (
    <Page
      title="Talabalar"
      subtitle={
        view === 'yuz'
          ? "Kim yuzini topshirgan, kim yo'q"
          : formatUzDate(date, { weekday: true })
      }
      breadcrumbs={[{ label: 'Talabalar' }]}
      actions={<IconButton icon={RefreshCw} label="Yangilash" variant="secondary" onClick={overview.reload} loading={overview.refreshing} />}
      tabs={data ? views : undefined}
      defaultTab={defaultView}
      tabParam={VIEW_PARAM}
      toolbar={
        !presentation && view === 'davomat' ? (
          <Toolbar>
            <QuickSearch date={date} withDate={withDate} />
          </Toolbar>
        ) : undefined
      }
    >
      {overview.loading ? (
        <>
          <SkeletonTiles count={3} className="xl:grid-cols-3" />
          <SkeletonCards count={4} />
        </>
      ) : overview.error && !data ? (
        <ErrorState variant="block" message={overview.error} onRetry={overview.reload} />
      ) : data && s && view === 'yuz' ? (
        <EnrollmentCampaign today={today} withDate={withDate} />
      ) : data && s ? (
        <div className="flex min-w-0 flex-col gap-3">
          {!available && (
            <div role="status" className="print-hide flex flex-col gap-3 border border-warning/50 bg-warning-soft px-3 py-2 text-[13px] text-fg sm:flex-row sm:items-center">
              <AlertTriangle size={16} className="shrink-0 text-warning" aria-hidden="true" />
              <p className="flex-1">
                Talabalarning {formatPercent(data.studentsEnrolledPct, 1)} qismi yuzini topshirgan. Foizlar faqat {formatNumber(s.enrolled)} talaba bo&apos;yicha.
              </p>
              <Button size="sm" icon={ScanFace} onClick={() => setView('yuz')}>
                Yuz topshirish
              </Button>
            </div>
          )}
          {overview.error && <StaleNote message={overview.error} onRetry={overview.reload} />}

          {faculties.length === 0 ? (
            <EmptyState title="Fakultetlar hali kelmagan" description="Fakultetlar HEMIS'dan avtomatik olinadi — «Tizim holati» sahifasida HEMIS sinxronlashini tekshiring." />
          ) : (
            <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_20rem]">
              <IntelPanel title="Fakultetlar" code={`${faculties.length} ta`}>
                {/* Uchta son — qolgani taxtaning o'zida. */}
                <KpiReadout
                  className="lg:grid-cols-4"
                  items={[
                    {
                      label: 'Davomat',
                      value: formatPercent(s.rate, 1),
                      rate: s.rate,
                      hint: `${formatNumber(s.present)} keldi / ${formatNumber(s.present + s.absent + s.notYet)} kelishi kerak (yuzi bazada borlar)`,
                    },
                    {
                      label: 'Kech keldi',
                      value: formatNumber(s.late),
                      unit: 'talaba',
                      hint: 'Kelganlar ichida — ish boshlanishidan kech',
                    },
                    {
                      label: isToday ? 'Kelmadi / hali yo‘q' : 'Kelmadi',
                      value: formatNumber(s.absent + (isToday ? s.notYet : 0)),
                      unit: 'talaba',
                      hint: isToday
                        ? `${formatNumber(s.notYet)} tasi hali kelishi mumkin (kun tugamagan)`
                        : 'Yuzi bazada bor, kamera kun bo‘yi ko‘rmagan',
                    },
                    {
                      label: 'Yuzi yo‘q',
                      value: formatNumber(s.total - s.enrolled),
                      unit: 'talaba',
                      hint: 'Kamera taniy olmaydi — foizga kirmaydi. «Yuz topshirish» bo‘limiga qarang',
                    },
                  ]}
                />
                <div className="border-t border-border">
                  <StatusBoard items={sortedBoard} onOpen={(id) => navigate(withDate(situationPaths.faculty(id === 'none' ? null : id)))} />
                </div>
                <RagLegend />
                {emptyFaculties > 0 && (
                  <p className="px-3 pb-2 text-[11px] text-muted">
                    Yana {emptyFaculties} ta fakultetga hali talaba biriktirilmagan — ro‘yxatda ko‘rsatilmadi.
                  </p>
                )}
              </IntelPanel>

              <LiveArrivals items={arrivals} live={isToday} linkFor={(id) => withDate(situationPaths.person(id))} className="self-start" />
            </div>
          )}
          {faculties.length > 0 && available && <WeakestGroups date={date} withDate={withDate} />}
        </div>
      ) : null}
    </Page>
  );
}
