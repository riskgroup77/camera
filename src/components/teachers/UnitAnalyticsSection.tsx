import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Award, CalendarCheck2, Clock3, Timer } from 'lucide-react';
import { Avatar, Card, CardHeader, DataTable, ErrorState, ProgressBar, SkeletonTiles, StatTile, cn, formatPercent, formatUzRange, toneForRate, type DataTableColumn } from '../../ui';
import { getAnalyticsPeople, getAnalyticsUnits, situationPaths, type PersonRank, type UnitKind } from '../../lib/situationApi';
import { useViewDate } from '../../lib/viewDate';
import { DeltaBadge } from '../analytics';
import { StreakBadge } from './RankingTab';
import { useLoader } from './useLoader';

const PEOPLE_LIMIT = 500;

function weightedRate(rows: Array<{ presentDays: number; absentDays: number }>): number | null {
  const present = rows.reduce((a, r) => a + r.presentDays, 0);
  const absent = rows.reduce((a, r) => a + r.absentDays, 0);
  return present + absent ? (present / (present + absent)) * 100 : null;
}

/** Bo'linma sahifasidagi mini "Tahlil": davr KPI (oldingi davr va institut
 *  o'rtachasiga nisbatan), bo'linmalar orasidagi o'rni va xodimlar jadvali. */
export function UnitAnalyticsSection({ unitId, unitName, kind, from, to }: { unitId: string; unitName: string; kind: UnitKind; from: string; to: string }) {
  const navigate = useNavigate();
  const { withDate } = useViewDate();
  const units = useLoader(`ua:${from}:${to}`, (signal) => getAnalyticsUnits({ from, to, kind: 'all', sort: 'rate' }, { signal }), { group: 'ua' });
  const people = useLoader(`up:${unitId}:${from}:${to}`, (signal) => getAnalyticsPeople({ from, to, unitId, sort: 'late', limit: PEOPLE_LIMIT }, { signal }), { group: 'up' });
  // Server chegarasiga tegilsa jadval bo'linmaning HAMMA xodimi emas —
  // buni aytmasa, ro'yxatda yo'q odam "tahlilga tushmagan" deb o'qilardi.
  const peopleCapped = (people.data?.length ?? 0) >= PEOPLE_LIMIT;

  const unit = units.data?.find((u) => u.id === unitId) ?? null;
  // O'rin serverning qaytarish tartibiga ishonib hisoblanardi. Endi ro'yxat
  // shu yerda davomat bo'yicha kamayish tartibida saralanadi — "N-o'rin"
  // yonidagi foiz bilan doim mos tushadi.
  const ranked = useMemo(
    () => (units.data ?? []).filter((u) => u.rate !== null && u.kind !== 'lavozim').sort((a, b) => (b.rate ?? 0) - (a.rate ?? 0)),
    [units.data],
  );
  const position = unit ? ranked.findIndex((u) => u.id === unit.id) + 1 : 0;
  // O'rtacha ham reyting bilan bir xil to'plamdan: "Lavozim bo'yicha" soxta
  // bo'linmasi o'rinlar ro'yxatidan chiqarilgani holda o'rtachaga kirsa,
  // "N-o'rin" va "institut o'rtachasi" boshqa-boshqa institutni bildirardi.
  const institute = useMemo(() => weightedRate((units.data ?? []).filter((u) => u.kind !== 'lavozim')), [units.data]);
  const vsInstitute = unit?.rate !== null && unit?.rate !== undefined && institute !== null ? unit.rate - institute : null;

  const columns: DataTableColumn<PersonRank>[] = [
    {
      key: 'name',
      header: 'Xodim',
      sortValue: (p) => p.fullName,
      cell: (p) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={p.fullName} src={p.photoUrl ?? undefined} size="sm" />
          <div className="min-w-0">
            <p className="truncate font-medium text-fg" title={p.fullName}>
              {p.fullName}
            </p>
            <StreakBadge p={p} />
          </div>
        </div>
      ),
    },
    {
      key: 'rate',
      header: 'Davomat',
      width: '11rem',
      sortValue: (p) => p.rate,
      cell: (p) => (
        <div className="flex items-center gap-2">
          <span className="w-10 text-right text-sm font-semibold tabular-nums">{formatPercent(p.rate)}</span>
          <ProgressBar value={p.rate} size="xs" className="flex-1" />
        </div>
      ),
    },
    { key: 'arrival', header: "O'rt. kelish", align: 'right', sortValue: (p) => p.avgArrivalMinutes, cell: (p) => <span className="tabular-nums">{p.avgArrival ?? '—'}</span> },
    {
      key: 'late',
      header: 'Kech',
      align: 'right',
      sortValue: (p) => p.lateDays,
      sortFirst: 'desc',
      cell: (p) => <span className={cn('tabular-nums', p.lateDays >= 3 && 'font-semibold text-warning')}>{p.lateDays}</span>,
    },
    {
      key: 'absent',
      header: "Yo'q",
      align: 'right',
      sortValue: (p) => p.absentDays,
      sortFirst: 'desc',
      cell: (p) => <span className={cn('tabular-nums', p.absentDays >= 3 && 'font-semibold text-danger')}>{p.absentDays}</span>,
    },
    { key: 'present', header: 'Keldi (kun)', align: 'right', hideOnMobile: true, sortValue: (p) => p.presentDays, sortFirst: 'desc', cell: (p) => <span className="tabular-nums">{p.presentDays}</span> },
  ];

  return (
    <>
      {units.error && !units.data ? (
        <ErrorState variant="block" message={units.error} onRetry={units.reload} />
      ) : units.loading ? (
        <SkeletonTiles count={4} />
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Davomat (davr)"
            icon={CalendarCheck2}
            tone={toneForRate(unit?.rate)}
            value={formatPercent(unit?.rate, 1)}
            progress={unit?.rate}
            delta={unit?.trend !== null && unit?.trend !== undefined ? { value: Number(unit.trend.toFixed(1)), better: 'up', display: `${unit.trend > 0 ? '+' : ''}${unit.trend.toFixed(1)} pp` } : null}
            hint={
              // `unit` topilmasa sabab boshqa: bo'linma davr tahliliga umuman
              // tushmagan. Ilgari bu holat ham "oldingi davrda ma'lumot yo'q"
              // derdi va odam noto'g'ri xulosa chiqarardi.
              !unit
                ? "Bu bo'linma tanlangan davr tahlilida yo'q"
                : unit.previousRate !== null && unit.previousRate !== undefined
                  ? `avval ${formatPercent(unit.previousRate, 1)}`
                  : "oldingi davrda ma'lumot yo'q"
            }
          />
          <StatTile
            label="Institut o'rtachasiga nisbatan"
            icon={Award}
            tone={vsInstitute === null ? 'neutral' : vsInstitute >= 0 ? 'success' : 'danger'}
            value={position ? `${position}-o'rin` : '—'}
            unit={ranked.length ? `/ ${ranked.length}` : undefined}
            hint={
              <span className="inline-flex items-center gap-1.5">
                <DeltaBadge value={vsInstitute} unit="pp" /> institut {formatPercent(institute, 1)}
              </span>
            }
          />
          <StatTile
            label="O'rtacha kelish"
            icon={Clock3}
            tone="info"
            value={unit?.avgArrival ?? '—'}
            hint={unit?.punctualPct === null || unit?.punctualPct === undefined ? "Ma'lumot yo'q" : `kelgan kunlarning ${formatPercent(unit.punctualPct)} qismida o'z vaqtida`}
          />
          <StatTile
            label="Kech / kelmagan"
            icon={Timer}
            tone={unit && unit.lateDays + unit.absentDays ? 'warning' : 'neutral'}
            value={unit ? `${unit.lateDays} / ${unit.absentDays}` : '—'}
            unit="odam-kun"
            hint={unit ? `${unit.headcount} xodim · ${unit.enrolled} yuzi bor` : undefined}
          />
        </div>
      )}

      <Card padding="none">
        <div className="p-4 pb-2 sm:px-5">
          <CardHeader title={`${unitName} — xodimlar`} subtitle={`${formatUzRange(from, to)} · ${kind === 'lavozim' ? 'lavozim bo\'yicha' : 'ustunni bosib saralang'}${peopleCapped ? ` · eng ko'p kechikkan ${PEOPLE_LIMIT} xodim ko'rsatilmoqda` : ''}`} className="mb-0" />
        </div>
        <DataTable
          columns={columns}
          rows={people.data ?? []}
          rowKey={(p) => p.id}
          loading={people.loading}
          error={people.data ? null : people.error}
          onRetry={people.reload}
          onRowClick={(p) => navigate(withDate(situationPaths.person(p.id)))}
          defaultSort={{ key: 'late', dir: 'desc' }}
          emptyTitle="Bu davrda ma'lumot yo'q"
          emptyDescription="Xodimlarning yuzi tasdiqlanib, kameralar ularni tanigach tahlil paydo bo'ladi."
          ariaLabel="Bo'linma xodimlari tahlili"
        />
      </Card>
    </>
  );
}
