import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, CalendarDays, Download, Gauge, LayoutGrid, List, Printer, Send, TriangleAlert } from 'lucide-react';
import {
  Button,
  CodeText,
  DateRangePicker,
  DocumentHeader,
  ErrorState,
  IntelPanel,
  Readout,
  Page,
  SkeletonCard,
  Tabs,
  cn,
  formatUzRange,
  useToast,
  type TabItem,
} from '../../ui';
import { RAG_LETTER, RAG_TEXT, RATE_RAG, rag } from '../../ui/rag';
import CriteriaStrip from '../../components/hisobot/CriteriaStrip';
import KpiStrip from '../../components/hisobot/KpiStrip';
import KpiView from '../../components/hisobot/KpiView';
import InstituteStatusView from '../../components/hisobot/InstituteStatusView';
import ReportSchedulesDialog from '../../components/hisobot/ReportSchedulesDialog';
import PeopleTable from '../../components/hisobot/PeopleTable';
import { RagLegend, StatusBoard, boardRag, type BoardItem } from '../../components/hisobot/board';
import ReportFilters from '../../components/reports/ReportFilters';
import TabelView from '../../components/reports/TabelView';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { branding } from '../../lib/branding';
import { downloadBlob } from '../../lib/download';
import { useApiResource } from '../../lib/useApiResource';
import { formatUzMonth } from '../../lib/uzDate';
import {
  PERIOD_PRESETS,
  SECTION_KIND,
  documentReference,
  drillPatch,
  hisobotPaths,
  readState,
  writeState,
  type HisobotFilterOptions,
  type HisobotReport,
  type HisobotSection,
  type HisobotState,
  type HisobotView,
} from '../../lib/hisobotApi';
import { tabelExcelFilename, tabelExcelHref, tabelPaths, type TabelReport } from '../../lib/tabelApi';
import DayOffNotice from '../../components/situation/DayOffNotice';

/**
 * Hisobotlar — rahbar uchun.
 *
 * To'rtta ko'rinish, bittadan vazifa bilan:
 *   HOLAT TAXTASI — "qayerda muammo bor?" Bo'linmalar svetofor bilan,
 *                   yomoni birinchi. Bosilsa o'sha bo'linmaga kiradi.
 *   RO'YXAT       — "kim?" Har qator bitta odam.
 *   OYLIK TABEL   — imzolanadigan hujjat (kun-kun jadval).
 *   KPI           — rahbariyat paneli: davomat, yuzni tanish, xavfsizlik,
 *                   kameralar — bir ekranda, oldingi davrga nisbatan.
 *
 * Butun holat URL'da: havola ulashiladi, "orqaga" ishlaydi.
 */

const SECTIONS: TabItem<HisobotSection>[] = [
  { id: 'xodimlar', label: 'Xodimlar' },
  { id: 'talabalar', label: 'Talabalar' },
];

const VIEWS: TabItem<HisobotView>[] = [
  { id: 'holat', label: 'Umumiy holat', icon: Activity },
  { id: 'taxta', label: 'Holat taxtasi', icon: LayoutGrid },
  { id: 'royxat', label: "Ro'yxat", icon: List },
  { id: 'tabel', label: 'Oylik tabel', icon: CalendarDays },
  { id: 'kpi', label: 'KPI', icon: Gauge },
];

function stamp(): string {
  try {
    return new Intl.DateTimeFormat('ru-RU', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'Asia/Tashkent',
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 16).replace('T', ' ');
  }
}

export default function HisobotPage() {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => readState(params), [params]);
  const { token, role } = useAuth();
  const { can } = usePermissions();
  const toast = useToast();
  const [exporting, setExporting] = useState(false);
  const [schedulesOpen, setSchedulesOpen] = useState(false);

  const kind = SECTION_KIND[state.section];
  const tabel = state.view === 'tabel';
  // KPI butun institut bo'yicha: bo'lim, mezon va aholi filtrlari unga tegishli emas.
  const kpi = state.view === 'kpi';
  // Umumiy holat — o'z filtrlari va jonli ma'lumoti bilan (InstituteStatusView).
  const holat = state.view === 'holat';
  const options = useApiResource<HisobotFilterOptions>(kpi || holat ? null : hisobotPaths.filters(kind));
  const report = useApiResource<HisobotReport>(tabel || kpi || holat ? null : hisobotPaths.report(state));
  const sheet = useApiResource<TabelReport>(tabel ? tabelPaths.data(state) : null);

  // Bo'lim almashganda oldingi bo'limning ma'lumoti ko'rinib qolmasin.
  const data = report.data && report.data.kind === kind ? report.data : null;
  const [sheetSection, setSheetSection] = useState(state.section);
  useEffect(() => {
    if (sheet.data) setSheetSection(state.section);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- faqat yangi javob kelganda
  }, [sheet.data]);
  const sheetData =
    sheet.data && sheet.data.month === state.month && sheetSection === state.section ? sheet.data : null;

  const update = useCallback(
    (patch: Partial<HisobotState>) => setParams((prev) => writeState(prev, patch), { replace: true }),
    [setParams],
  );
  const reset = useCallback(
    () => update({ faculty: '', course: '', group: '', unitKind: '', unit: '', q: '' }),
    [update],
  );

  const criterion = data?.criterion ?? state.criterion;
  const reference = useMemo(() => documentReference(state), [state]);
  const generatedAt = useMemo(stamp, [state, data, sheetData]);
  const ready = kpi || holat || (tabel ? Boolean(sheetData) : Boolean(data));
  const loading = kpi || holat ? false : tabel ? sheet.loading : report.loading;

  async function exportExcel() {
    if (exporting) return;
    if (!tabel && !criterion) return;
    setExporting(true);
    try {
      const path = tabel ? tabelPaths.excel(state) : hisobotPaths.export(state, criterion);
      const blob = await api.blob(path, token);
      const filename = tabel
        ? tabelExcelFilename(state)
        : `hisobot-${state.section}-${criterion}-${state.from}_${state.to}.xlsx`;
      downloadBlob(blob, filename);
      toast.success(`${filename} yuklab olindi`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Excel faylni yuklab bo'lmadi — qaytadan urinib ko'ring");
    } finally {
      setExporting(false);
    }
  }

  // Taxtadagi kataklar — serverning "kesim" qatorlaridan.
  const board: BoardItem[] = useMemo(() => {
    const rows = data?.report.breakdown?.rows ?? [];
    const unit = data?.report.breakdown?.unit ?? '';
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      value: row.value,
      unit,
      detail: row.detail,
      headcount: row.headcount,
    }));
  }, [data, state.section]);

  // Yomoni birinchi: rahbar ekranning yuqorisidan chora kerak bo'lgan
  // joyni topadi, pastga qarab tinchlanadi.
  const sortedBoard = useMemo(() => {
    const order = { qizil: 0, sariq: 1, yashil: 2, yoq: 3 } as const;
    return [...board].sort((a, b) => {
      const byTone = order[boardRag(a, RATE_RAG)] - order[boardRag(b, RATE_RAG)];
      if (byTone !== 0) return byTone;
      return (a.value ?? Infinity) - (b.value ?? Infinity);
    });
  }, [board]);


  // Binolar kesimi (forma) bo'linma filtri emas — ustiga bosib bo'lmaydi.
  const canDrill = data ? data.report.breakdown?.drill !== false && drillPatch(state, '_') !== null : false;

  const scope = kpi ? 'Butun institut' : tabel ? sheetData?.scope : data?.scope;
  const period = kpi
    ? formatUzRange(state.from, state.to)
    : tabel
    ? sheetData?.monthLabel || formatUzMonth(state.month)
    : data
      ? formatUzRange(data.period.from, data.period.to)
      : '—';
  const population = tabel
    ? sheetData
      ? `${(sheetData.totals?.people ?? sheetData.people.length).toLocaleString('ru-RU')} kishi`
      : '—'
    : data
      ? `${data.population.total.toLocaleString('ru-RU')} kishi`
      : '—';

  // Umumiy hukm — birinchi foizli plitkadan.
  const headline = useMemo(() => {
    const tile = data?.report.tiles.find((t) => t.unit === '%');
    if (!tile) return null;
    const numeric = typeof tile.value === 'number' ? tile.value : Number(String(tile.value).replace(',', '.'));
    return { value: numeric, tone: rag(Number.isFinite(numeric) ? numeric : null, RATE_RAG), label: tile.label };
  }, [data]);

  return (
    <Page
      title="Hisobotlar"
      actions={
        <span className="flex gap-2 print-hide">
          {can('manageNotifications', role) && (
            <Button variant="secondary" icon={Send} onClick={() => setSchedulesOpen(true)}>
              Avtomatik yuborish
            </Button>
          )}
          <Button variant="secondary" icon={Printer} onClick={() => window.print()} disabled={!ready || loading}>
            Chop etish
          </Button>
          {kpi ? null : tabel ? (
            <a
              href={tabelExcelHref(state)}
              data-tabel-excel
              className={cn(
                'inline-flex items-center gap-1.5 border border-border bg-surface px-3 py-1.5 text-[13px]',
                (!ready || exporting) && 'pointer-events-none opacity-60',
              )}
              onClick={(event) => {
                event.preventDefault();
                if (!ready || exporting) return;
                void exportExcel();
              }}
              aria-disabled={!ready || exporting}
              aria-busy={exporting}
              tabIndex={!ready || exporting ? -1 : undefined}
            >
              <Download size={15} aria-hidden="true" />
              {exporting ? 'Tayyorlanmoqda…' : 'Excel'}
            </a>
          ) : (
            <Button variant="secondary" icon={Download} onClick={exportExcel} loading={exporting} disabled={!data}>
              Excel
            </Button>
          )}
        </span>
      }
    >
      <div className="flex min-w-0 flex-col gap-3">
        {/* Hujjat blanki faqat tabelda: u qog'ozga chiqadi va imzolanadi.
            Boshqa ko'rinishlarda sarlavha va uchta raqam yetarli. */}
        {tabel ? (
          <DocumentHeader
            org={branding.orgFullName}
            title="Davomat tabeli"
            reference={reference}
            generatedAt={generatedAt}
            readouts={[
              { label: 'Qamrov', value: scope ?? '—', title: scope ?? undefined },
              { label: 'Oy', value: period },
              { label: "Ro'yxatda", value: population },
            ]}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border border-border bg-surface px-3 py-2">
            <Readout label="Qamrov" value={scope ?? '—'} title={scope ?? undefined} />
            <Readout label="Davr" value={period} />
            {!kpi && <Readout label="Ro'yxatda" value={population} />}
            {!kpi && headline && (
              <span className="ms-auto flex items-baseline gap-2">
                <CodeText className={cn('text-[28px] font-semibold leading-none', RAG_TEXT[headline.tone])}>
                  {Math.round(headline.value * 10) / 10}%
                </CodeText>
                <CodeText className={cn('text-[12px] font-bold', RAG_TEXT[headline.tone])}>
                  {RAG_LETTER[headline.tone]}
                </CodeText>
              </span>
            )}
          </div>
        )}

        {/* 2. Boshqaruv: bo'lim, ko'rinish, filtrlar. */}
        <div className="print-hide flex flex-col gap-2 border border-border bg-surface">
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
            {!kpi && (
              <Tabs tabs={SECTIONS} value={state.section} onChange={(section) => update({ section })} ariaLabel="Bo'lim" />
            )}
            <Tabs
              tabs={VIEWS}
              value={state.view}
              onChange={(view) => update({ view })}
              variant="segmented"
              size="sm"
              ariaLabel="Ko'rinish"
              className="sm:ms-auto"
            />
          </div>
          {!tabel && !kpi && !holat && (
            <CriteriaStrip
              criteria={data?.criteria ?? null}
              value={criterion}
              onChange={(key) => update({ criterion: key })}
              loading={report.loading}
            />
          )}
          {!holat && <div className="px-3 pb-2">
            {kpi ? (
              <DateRangePicker
                value={{ preset: state.preset, from: state.from, to: state.to }}
                presets={PERIOD_PRESETS}
                onChange={(v) => update({ preset: v.preset, from: v.from, to: v.to })}
                showSummary={false}
              />
            ) : (
              <ReportFilters state={state} options={options.data} onChange={update} onReset={reset} />
            )}
          </div>}
        </div>

        {/* Bir kunlik davr dam olish/bayramga tushsa — nima uchun hammasi 0 ekanini aytamiz. */}
        {!holat && !kpi && state.from === state.to && (
          <DayOffNotice
            date={state.from}
            onPick={(day) => update({ preset: 'custom', from: day, to: day })}
          />
        )}

        {/* 3. Javob. */}
        {holat ? (
          <InstituteStatusView type={kind} />
        ) : kpi ? (
          <KpiView from={state.from} to={state.to} />
        ) : tabel ? (
          sheet.error && !sheetData ? (
            <ErrorState title="Tabelni yuklab bo'lmadi" message={sheet.error} onRetry={sheet.reload} />
          ) : !sheetData ? (
            <SkeletonCard />
          ) : (
            <div className={sheet.loading ? 'opacity-70 transition-opacity' : undefined}>
              {sheet.error && <StaleWarning message={sheet.error} onRetry={sheet.reload} />}
              <TabelView data={sheetData} section={state.section} reference={reference} />
            </div>
          )
        ) : report.error && !data ? (
          <ErrorState title="Hisobotni yuklab bo'lmadi" message={report.error} onRetry={report.reload} />
        ) : !data ? (
          <SkeletonCard />
        ) : (
          <div className={cn('flex min-w-0 flex-col gap-3', report.loading && 'opacity-70 transition-opacity')}>
            {report.error && <StaleWarning message={report.error} onRetry={report.reload} />}

            <IntelPanel title="Asosiy ko'rsatkichlar">
              <KpiStrip tiles={data.report.tiles} />
            </IntelPanel>


            {state.view === 'taxta' ? (
              <>

                <IntelPanel
                  title={data.report.breakdown?.title ?? "Bo'linmalar holati"}
                  code={`${board.length} ta`}
                >
                  <StatusBoard
                    items={sortedBoard}
                    onOpen={canDrill ? (id) => {
                      const patch = drillPatch(state, id);
                      if (patch) update(patch);
                    } : undefined}
                  />
                  <RagLegend />
                </IntelPanel>
              </>
            ) : (
              <IntelPanel
                title={data.report.people_title}
                code={`${data.report.people_total.toLocaleString('ru-RU')} ta`}
              >
                <PeopleTable data={data} />
              </IntelPanel>
            )}

          </div>
        )}
      </div>
      <ReportSchedulesDialog open={schedulesOpen} onClose={() => setSchedulesOpen(false)} />
    </Page>
  );
}

/** Ekrandagi sonlar eskirgan bo'lishi mumkin — chop etib yubormasin. */
function StaleWarning({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <p
      role="alert"
      className="print-hide flex flex-wrap items-center gap-2 border border-warning/50 bg-warning-soft px-3 py-2 text-[13px] text-fg"
    >
      <TriangleAlert size={15} aria-hidden="true" className="shrink-0" />
      <span>Ko&apos;rsatilayotgan ma&apos;lumot eskirgan bo&apos;lishi mumkin: {message}</span>
      <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">
        Qayta urinish
      </button>
    </p>
  );
}
