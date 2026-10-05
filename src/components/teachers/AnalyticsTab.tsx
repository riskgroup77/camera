import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarCheck2, Clock3, Timer, UserX } from 'lucide-react';
import {
  Card,
  CardHeader,
  DataTable,
  DateRangePicker,
  EmptyState,
  ErrorState,
  ProgressBar,
  Skeleton,
  StatTile,
  Tabs,
  Toolbar,
  cn,
  formatNumber,
  formatPercent,
  formatUzDate,
  formatUzRange,
  toneForRate,
  type DataTableColumn,
} from '../../ui';
import {
  getAnalyticsHeatmap,
  getAnalyticsSummary,
  getAnalyticsUnits,
  situationPaths,
  UNIT_KIND_LABELS,
  type AnalyticsSummary,
  type UnitAnalytics,
} from '../../lib/situationApi';
import { useViewDate } from '../../lib/viewDate';
import { DeltaBadge, Heatmap, TrendChart, TrendLegend, clockToMinutes } from '../analytics';
import { ANALYTICS_PRESETS, useAnalyticsPeriod, useUrlChoice } from './analyticsPeriod';
import { useLoader } from './useLoader';

type KindFilter = 'all' | 'kafedra' | 'dekanat' | 'bolim';

const KIND_FILTERS: readonly KindFilter[] = ['all', 'kafedra', 'dekanat', 'bolim'];

function kpiDelta(value: number | null | undefined, better: 'up' | 'down', suffix: string, digits = 1) {
  if (value === null || value === undefined) return null;
  const r = Number(value.toFixed(digits));
  return { value: r, better, display: `${r > 0 ? '+' : ''}${r.toLocaleString('ru-RU', { maximumFractionDigits: digits })}${suffix}` };
}

/** Davr hikoyasi: eng yaxshi / eng past kun, maqsaddan past kunlar soni. */
function storyLine(s: AnalyticsSummary): string | null {
  const days = s.daily.filter((d) => d.rate !== null);
  if (days.length < 2) return null;
  const best = days.reduce((a, b) => ((b.rate ?? 0) > (a.rate ?? 0) ? b : a));
  const worst = days.reduce((a, b) => ((b.rate ?? 101) < (a.rate ?? 101) ? b : a));
  const below = days.filter((d) => (d.rate ?? 0) < 85).length;
  const fmt = (iso: string) => formatUzDate(iso, { weekday: true, year: false });
  return `Eng yaxshi kun — ${fmt(best.date)} (${formatPercent(best.rate)}), eng past — ${fmt(worst.date)} (${formatPercent(worst.rate)}). ${
    below ? `${below} kun maqsaddan (85%) past.` : "Barcha kunlar maqsaddan yuqori."
  }`;
}

/** "Tahlil" tabi: KPI (oldingi davrga nisbatan), kunlik trend, hafta×soat
 *  issiqlik xaritasi, hafta kunlari bo'yicha kechikish, bo'linmalar reytingi. */
export function AnalyticsTab() {
  const [period, setPeriod] = useAnalyticsPeriod();
  const navigate = useNavigate();
  const { withDate } = useViewDate();
  // Bo'linma turi URL'da — yangilashdan keyin ham o'sha jadval qaytadi.
  const [kind, setKind] = useUrlChoice<KindFilter>('turi', KIND_FILTERS, 'all');
  const key = `${period.from}:${period.to}`;
  const range = { from: period.from, to: period.to, type: 'xodim' as const };
  const summary = useLoader(`s:${key}`, (signal) => getAnalyticsSummary(range, { signal }), { group: 'summary' });
  const heatmap = useLoader(`h:${key}`, (signal) => getAnalyticsHeatmap(range, { signal }), { group: 'heatmap' });
  const units = useLoader(`u:${key}:${kind}`, (signal) => getAnalyticsUnits({ ...range, kind }, { signal }), { group: 'units' });

  const s = summary.data;
  const noPrev = s ? s.previous.daysCovered === 0 : false;
  const prevHint = s ? (noPrev ? "Oldingi davrda ma'lumot yo'q" : `oldingi: ${formatUzRange(s.previousFrom, s.previousTo)}`) : undefined;
  const points = useMemo(
    () => (s?.daily ?? []).filter((d) => d.expected > 0).map((d) => ({ date: d.date, rate: d.rate, arrivalMinutes: clockToMinutes(d.avgArrival) })),
    [s],
  );

  const unitColumns: DataTableColumn<UnitAnalytics>[] = [
    {
      key: 'name',
      header: "Bo'linma",
      sortValue: (u) => u.name,
      cell: (u) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-fg">{u.name}</p>
          <p className="text-xs text-muted">
            {UNIT_KIND_LABELS[u.kind]} · {u.headcount} kishi
          </p>
        </div>
      ),
    },
    {
      key: 'rate',
      header: 'Davomat',
      width: '13rem',
      sortValue: (u) => u.rate,
      sortFirst: 'desc',
      cell: (u) => (
        <div className="flex items-center gap-2">
          <span className="w-10 text-right text-sm font-semibold tabular-nums text-fg">{formatPercent(u.rate)}</span>
          <ProgressBar value={u.rate} size="xs" className="flex-1" />
        </div>
      ),
    },
    { key: 'trend', header: 'Trend', align: 'right', sortValue: (u) => u.trend, sortFirst: 'desc', cell: (u) => <DeltaBadge value={u.trend} unit="pp" emptyLabel="—" /> },
    { key: 'arrival', header: "O'rt. kelish", align: 'right', sortValue: (u) => u.avgArrivalMinutes, cell: (u) => <span className="tabular-nums">{u.avgArrival ?? '—'}</span> },
    {
      key: 'punctual',
      header: "O'z vaqtida",
      align: 'right',
      hideOnMobile: true,
      sortValue: (u) => u.punctualPct,
      sortFirst: 'desc',
      cell: (u) => <span className={cn('tabular-nums', u.punctualPct !== null && u.punctualPct < 80 && 'font-semibold text-warning')}>{formatPercent(u.punctualPct)}</span>,
    },
    { key: 'late', header: 'Kech (kun)', align: 'right', hideOnMobile: true, sortValue: (u) => u.lateDays, sortFirst: 'desc' , cell: (u) => <span className="tabular-nums">{u.lateDays}</span> },
    { key: 'absent', header: "Yo'q (kun)", align: 'right', hideOnMobile: true, sortValue: (u) => u.absentDays, sortFirst: 'desc', cell: (u) => <span className="tabular-nums">{u.absentDays}</span> },
  ];

  const hm = heatmap.data;
  // Bo'sh chekka soatlarni kesish (kamida 6 soatlik oyna qoladi).
  const hourWindow = useMemo(() => {
    if (!hm) return { start: 0, end: 0 };
    const used = hm.hours.map((_, i) => hm.weekdays.some((w) => (w.counts[i] ?? 0) > 0));
    let start = Math.max(0, used.indexOf(true) - 1);
    let end = used.lastIndexOf(true) === -1 ? hm.hours.length - 1 : Math.min(hm.hours.length - 1, used.lastIndexOf(true) + 1);
    if (used.indexOf(true) === -1) start = 0;
    while (end - start < 7 && (start > 0 || end < hm.hours.length - 1)) {
      if (end < hm.hours.length - 1) end += 1;
      if (end - start < 7 && start > 0) start -= 1;
    }
    return { start, end: end + 1 };
  }, [hm]);
  // Haqiqiy maksimum (avval 1 dan boshlangani uchun barcha kechikish 1% dan
  // past bo'lgan haftada ustunlar ko'rinmay, "eng yomon kun" ham belgilanmasdi).
  const lateMax = hm ? Math.max(0, ...hm.weekdays.map((w) => w.lateRate ?? 0)) : 0;

  return (
    <>
      <Toolbar>
        <DateRangePicker value={period} onChange={setPeriod} presets={ANALYTICS_PRESETS} size="sm" />
        <p className="text-[13px] text-muted">Faqat xodimlar · kelajak kunlari hisobga olinmaydi</p>
      </Toolbar>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Davomat"
          icon={CalendarCheck2}
          tone={toneForRate(s?.current.rate)}
          loading={summary.loading}
          value={formatPercent(s?.current.rate, 1)}
          progress={s?.current.rate}
          // Oldingi davrda birorta ish kuni qamrab olinmagan bo'lsa
          // taqqoslash yo'q: "+100 pp" kabi son chiqib qolardi. Quyidagi
          // ikki plitka allaqachon shunday himoyalangan edi, bu ikkitasi yo'q.
          delta={noPrev ? null : kpiDelta(s?.delta.rate, 'up', ' pp')}
          hint={prevHint}
        />
        <StatTile
          label="O'rtacha kelish"
          icon={Clock3}
          tone="info"
          loading={summary.loading}
          value={s?.current.avgArrival ?? '—'}
          delta={noPrev ? null : kpiDelta(s?.delta.avgArrivalMinutes, 'down', ' daq', 0)}
          hint={s?.previous.avgArrival ? `avval ${s.previous.avgArrival}` : prevHint}
        />
        <StatTile
          label="Kech qolishlar"
          icon={Timer}
          tone={s && s.current.late ? 'warning' : 'neutral'}
          loading={summary.loading}
          value={formatNumber(s?.current.late)}
          unit="marta"
          delta={noPrev ? null : kpiDelta(s?.delta.late, 'down', '', 0)}
          hint={s ? `${formatPercent(s.current.punctualPct, 1)} o'z vaqtida` : undefined}
        />
        <StatTile
          label="Kelmagan kunlar"
          icon={UserX}
          tone={s && s.current.absent ? 'danger' : 'neutral'}
          loading={summary.loading}
          value={formatNumber(s?.current.absent)}
          unit="odam-kun"
          delta={noPrev ? null : kpiDelta(s?.delta.absent, 'down', '', 0)}
          hint={s ? `${s.current.daysCovered} ish kuni ma'lumoti` : undefined}
        />
      </div>

      <Card>
        <CardHeader title="Kunlik davomat va kelish vaqti" subtitle={s ? storyLine(s) ?? undefined : undefined} actions={<TrendLegend />} />
        {summary.error && !s ? (
          <ErrorState message={summary.error} onRetry={summary.reload} />
        ) : summary.loading ? (
          <Skeleton className="h-64 w-full" />
        ) : points.length === 0 ? (
          <EmptyState title="Bu davrda ma'lumot yo'q" description="Boshqa davrni tanlang." />
        ) : (
          <TrendChart points={points} height={280} />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Qachon kelishadi?" subtitle="Hafta kuni × soat bo'yicha kelishlar soni (birinchi kirish)" />
          {heatmap.error && !hm ? (
            <ErrorState message={heatmap.error} onRetry={heatmap.reload} />
          ) : !hm ? (
            <Skeleton className="h-52 w-full" />
          ) : (
            <>
              <Heatmap
                columns={hm.hours.slice(hourWindow.start, hourWindow.end).map((h) => `${String(h).padStart(2, '0')}:00`)}
                rows={hm.weekdays.map((w) => ({ label: w.label, values: w.counts.slice(hourWindow.start, hourWindow.end), aside: w.total ? `${w.total}` : '' }))}
                max={hm.max}
                ariaLabel="Kelishlar issiqlik xaritasi"
                formatTooltip={(row, c, v) => {
                  const h = String(hm.hours[c + hourWindow.start]).padStart(2, '0');
                  return `${row.label}, ${h}:00–${h}:59 — ${v} ta kelish`;
                }}
              />
              {hm.outside > 0 && <p className="mt-1 text-xs text-muted">Yakshanba yoki 06–20 dan tashqarida: {hm.outside} ta kelish</p>}
            </>
          )}
        </Card>
        <Card>
          <CardHeader title="Kechikish — hafta kunlari" subtitle="Kelganlardan kech qolganlar ulushi" />
          {/* Xato bo'lsa skelet abadiy aylanib turmasin — bu ikkala karta ham
              bitta issiqlik xaritasi so'rovidan chiziladi. */}
          {heatmap.error && !hm ? (
            <ErrorState message={heatmap.error} onRetry={heatmap.reload} />
          ) : !hm ? (
            <Skeleton className="h-52 w-full" />
          ) : (
            <ul className="space-y-2.5">
              {hm.weekdays.map((w) => {
                const worst = lateMax > 0 && w.lateRate !== null && w.lateRate === lateMax;
                return (
                  <li key={w.weekday} className="grid grid-cols-[2.5rem_1fr_3.5rem] items-center gap-2 text-sm">
                    <span className={cn('font-medium', worst ? 'text-fg' : 'text-muted')}>{w.label}</span>
                    <span className="h-3 overflow-hidden rounded-full bg-surface-2">
                      <span
                        className={cn('block h-full rounded-full transition-[width] duration-500', worst ? 'bg-warning' : 'bg-warning/45')}
                        style={{ width: lateMax > 0 ? `${((w.lateRate ?? 0) / lateMax) * 100}%` : '0%' }}
                      />
                    </span>
                    <span className="text-right tabular-nums text-fg">
                      {formatPercent(w.lateRate, 1)}
                      <span className="block text-[10px] text-muted">{w.late} marta</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <Card padding="none">
        <div className="flex flex-wrap items-center justify-between gap-3 p-4 pb-3 sm:px-5">
          <div>
            <h3 className="text-[15px] font-semibold text-fg">Bo'linmalar taqqoslash</h3>
            <p className="text-xs text-muted">Ustun sarlavhasini bosib saralang · trend — oldingi davrga nisbatan</p>
          </div>
          <Tabs
            variant="segmented"
            size="sm"
            value={kind}
            onChange={setKind}
            ariaLabel="Bo'linma turi"
            tabs={[
              { id: 'all', label: 'Hammasi' },
              { id: 'kafedra', label: 'Kafedralar' },
              { id: 'dekanat', label: 'Dekanatlar' },
              { id: 'bolim', label: "Bo'limlar" },
            ]}
          />
        </div>
        <DataTable
          columns={unitColumns}
          rows={units.data ?? []}
          rowKey={(u) => u.id}
          loading={units.loading}
          error={units.data ? null : units.error}
          onRetry={units.reload}
          onRowClick={(u) => navigate(withDate(situationPaths.kafedra(u.id)))}
          defaultSort={{ key: 'rate', dir: 'desc' }}
          emptyTitle="Bo'linma topilmadi"
          ariaLabel="Bo'linmalar taqqoslash"
        />
      </Card>
    </>
  );
}
