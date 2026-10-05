import { ChevronRight, TriangleAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getGroups, situationPaths, type GroupStat } from '../../lib/situationApi';
import { hasAttendanceData } from '../../lib/studentAttendance';
import { RAG_TEXT, formatNumber, formatPercent, rag, RATE_RAG, cn } from '../../ui';
import { IntelPanel } from '../../ui/intel';
import { useAsyncData } from './useAsyncData';

const LIMIT = 8;

/**
 * Davomati eng past guruhlar — "qayerga birinchi qarash kerak" savoliga
 * javob. Faqat o'lchangan (yuzi yetarli) guruhlar: 20 kishidan 2 tasi
 * tanilgan guruhning "10%" i kamera qamrovi, davomat emas.
 */
export function WeakestGroups({ date, withDate }: { date: string; withDate: (path: string) => string }) {
  const groups = useAsyncData<GroupStat[]>(`weak:${date}`, (signal) => getGroups({ date }, { signal }));
  const rows = (groups.data ?? [])
    .filter((g) => g.rate != null && hasAttendanceData(g) && g.enrolled >= 5)
    .sort((a, b) => (a.rate ?? 0) - (b.rate ?? 0))
    .slice(0, LIMIT);

  return (
    <IntelPanel title="Diqqat talab qiladigan guruhlar" code={rows.length ? `${rows.length} ta` : undefined}>
      {groups.loading && !groups.data ? (
        <p className="px-3 py-4 text-[13px] text-muted">Yuklanmoqda…</p>
      ) : groups.error && !groups.data ? (
        <p className="px-3 py-4 text-[13px] text-danger">Guruhlarni olib bo‘lmadi: {groups.error}</p>
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-[13px] text-muted">
          Bu kun bo‘yicha o‘lchangan guruh yo‘q (yuzi bazada kamida 5 talabasi bor guruhlar hisobga olinadi).
        </p>
      ) : (
        <>
          <p className="px-3 pt-2 text-[12px] text-muted">
            Davomati eng past guruhlar — bosing, guruhning har bir talabasi ko‘rinadi.
          </p>
          <ul className="divide-y divide-border">
            {rows.map((g) => {
              const tone = rag(g.rate, RATE_RAG);
              return (
                <li key={g.name}>
                  <Link
                    to={withDate(situationPaths.group(g.name))}
                    className="flex items-center gap-3 px-3 py-2 text-[13px] hover:bg-surface-2"
                  >
                    {tone === 'qizil' && <TriangleAlert size={14} className="shrink-0 text-danger" aria-hidden="true" />}
                    <span className="min-w-0 flex-1">
                      <b className="text-fg">{g.name}</b>
                      <span className="text-muted">
                        {' '}
                        · {g.faculty ?? 'Fakultetsiz'}
                        {g.course ? `, ${g.course}-kurs` : ''}
                      </span>
                    </span>
                    <span className="hidden text-[12px] text-muted sm:inline">
                      {formatNumber(g.absent)} kelmadi · {formatNumber(g.late)} kech
                    </span>
                    <b className={cn('w-14 text-right tabular-nums', RAG_TEXT[tone])}>{formatPercent(g.rate, 0)}</b>
                    <ChevronRight size={14} className="shrink-0 text-subtle" aria-hidden="true" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </IntelPanel>
  );
}
