import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react';
import { CodeText, ErrorState, IntelPanel, MicroLabel, SkeletonCard, cn } from '../../ui';
import { RAG_SOLID, RAG_TEXT } from '../../ui/rag';
import { useApiResource } from '../../lib/useApiResource';
import {
  formatMinutes,
  formatPct,
  kpiGroups,
  kpiPath,
  type KpiReport,
  type KpiTile,
  type Trend,
} from '../../lib/kpiApi';

/**
 * Rahbariyat KPI: to'rt savol — odamlar kelyaptimi, kamera taniyaptimi,
 * signallarga javob berilyaptimi, kameralar ishlayaptimi. Har raqam
 * svetofor bilan (rag.ts) va oldingi teng davrga nisbatan o'q bilan.
 */
export default function KpiView({ from, to }: { from: string; to: string }) {
  const res = useApiResource<KpiReport>(kpiPath(from, to));
  const data = res.data && res.data.period.from === from && res.data.period.to === to ? res.data : null;

  if (res.error && !data) return <ErrorState title="KPI yuklanmadi" message={res.error} onRetry={res.reload} />;
  if (!data) return <SkeletonCard />;

  return (
    <div className={cn('flex min-w-0 flex-col gap-3', res.loading && 'opacity-70 transition-opacity')}>
      {kpiGroups(data).map((group) => (
        <IntelPanel key={group.title} title={group.title}>
          <ul className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
            {group.tiles.map((tile) => (
              <Tile key={tile.key} tile={tile} />
            ))}
          </ul>
        </IntelPanel>
      ))}
      <IntelPanel title="Modullar" code={`${data.security.modules.length} ta`}>
        <ModuleTable data={data} />
      </IntelPanel>
    </div>
  );
}

function Tile({ tile }: { tile: KpiTile }) {
  return (
    <li className="flex flex-col gap-1.5 bg-surface px-3 py-2.5">
      <span className="flex items-center gap-2">
        {tile.rag !== 'yoq' && (
          <span aria-hidden="true" className={cn('h-2 w-2 shrink-0 rounded-[1px]', RAG_SOLID[tile.rag])} />
        )}
        <MicroLabel className="truncate">{tile.label}</MicroLabel>
      </span>
      <span className="flex items-baseline gap-2">
        <CodeText className={cn('text-[24px] font-semibold leading-none', tile.rag === 'yoq' ? 'text-fg' : RAG_TEXT[tile.rag])}>
          {tile.value}
        </CodeText>
        {tile.trend && <TrendMark trend={tile.trend} />}
      </span>
      {tile.hint && <span className="intel-code text-[11px] text-subtle">{tile.hint}</span>}
    </li>
  );
}

function TrendMark({ trend }: { trend: Trend }) {
  const Icon = trend.dir === 'up' ? ArrowUpRight : trend.dir === 'down' ? ArrowDownRight : ArrowRight;
  const tone = trend.good === null ? 'text-subtle' : trend.good ? 'text-success' : 'text-danger';
  const sign = trend.delta > 0 ? '+' : '';
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-[12px] font-medium', tone)} title="Oldingi davrga nisbatan">
      <Icon size={14} aria-hidden="true" />
      <CodeText>{`${sign}${trend.delta}`}</CodeText>
    </span>
  );
}

function ModuleTable({ data }: { data: KpiReport }) {
  const rows = data.security.modules;
  if (rows.length === 0) return <p className="px-3 py-2 text-[13px] text-subtle">Hodisa yo‘q</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-border text-left text-subtle">
            <th className="px-3 py-1.5 font-medium">Modul</th>
            <th className="px-3 py-1.5 text-right font-medium">Hodisa</th>
            <th className="px-3 py-1.5 text-right font-medium">Ko‘rilgan</th>
            <th className="px-3 py-1.5 text-right font-medium">Yolg‘on</th>
            <th className="px-3 py-1.5 text-right font-medium">Javob</th>
            <th className="px-3 py-1.5 text-right font-medium">Hal qilish</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.code} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5">{m.name}</td>
              <td className="intel-code px-3 py-1.5 text-right">{m.events}</td>
              <td className="intel-code px-3 py-1.5 text-right">{m.reviewed}</td>
              <td className="intel-code px-3 py-1.5 text-right">{formatPct(m.falsePct)}</td>
              <td className="intel-code px-3 py-1.5 text-right">{formatMinutes(m.reviewMinutes)}</td>
              <td className="intel-code px-3 py-1.5 text-right">{formatMinutes(m.resolveMinutes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
