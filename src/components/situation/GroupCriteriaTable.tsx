import { Link } from 'react-router-dom';
import { Video } from 'lucide-react';
import { DataTable, cn, type DataTableColumn } from '../../ui';
import {
  TONE_TEXT,
  criterionShort,
  workingCriteria,
  type CriterionCell,
  type CriterionTone,
  type GroupCriteria,
  type GroupCriteriaPerson,
} from '../../lib/groupCriteriaApi';

/**
 * Nazorat → guruh → "Kriteriyalar": har talaba qatorida hamma kriteriyalar.
 * Qiymat rangi — holat (yashil yaxshi, sariq ogohlantirish, qizil muammo),
 * kamera belgisi — 2 daqiqalik video dalillar (talaba sahifasida ko'riladi).
 * Faqat hisoblanayotgan kriteriyalar ustun bo'ladi (o'chiq yoki shu kun
 * tahlil qilinmaganlari — GroupTablePanel izohida, sababi bilan).
 */

const SEVERITY: Record<CriterionTone, number> = { danger: 3, warning: 2, neutral: 1, success: 0 };

/** Saralash: avval muammolisi, so'ng soni kattasi. */
export function cellSortValue(cell: CriterionCell | undefined): number {
  if (!cell || cell.value === '—') return -1;
  const number = Number.parseFloat(cell.value.replace(/[^\d.]/g, ''));
  return SEVERITY[cell.tone] * 10_000 + (Number.isFinite(number) ? number : 0);
}

function Cell({ cell }: { cell: CriterionCell | undefined }) {
  if (!cell) return <span className="text-subtle">—</span>;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap" title={cell.title}>
      <span className={cn('tabular-nums', cell.value === '—' ? 'text-subtle' : TONE_TEXT[cell.tone], cell.tone !== 'neutral' && 'font-semibold')}>
        {cell.value}
      </span>
      {cell.evidence ? (
        <span
          className="inline-flex items-center gap-0.5 rounded-full bg-primary-soft px-1.5 text-[10px] font-semibold text-primary"
          title={`${cell.evidence} ta 2 daqiqalik video dalil — talaba sahifasida`}
        >
          <Video className="h-3 w-3" aria-hidden="true" />
          {cell.evidence}
        </span>
      ) : null}
    </span>
  );
}

export default function GroupCriteriaTable({
  data,
  loading,
  error,
}: {
  data: GroupCriteria | null;
  loading: boolean;
  error: string | null;
}) {
  const criteria = workingCriteria(data?.criteria ?? []);
  const columns: DataTableColumn<GroupCriteriaPerson>[] = [
    { key: 'n', header: '№', width: '2.5rem', cell: (_r, i) => i + 1, mono: true },
    {
      key: 'name',
      header: 'F.I.Sh.',
      sortValue: (r) => r.full_name,
      cell: (r) => (
        // Ism bir qatorda: ustunlar ko'p — jadval yonga suriladi, ism esa uzilmaydi.
        <Link to={`/shaxs/${encodeURIComponent(r.id)}`} className="whitespace-nowrap font-medium text-fg hover:text-primary">
          {r.full_name}
          {!r.enrolled && <span className="ms-1 text-[11px] font-normal text-danger" title="Yuzi bazada yo‘q — kamera taniy olmaydi">· yuzsiz</span>}
        </Link>
      ),
    },
    ...criteria.map(
      (c): DataTableColumn<GroupCriteriaPerson> => ({
        key: c.key,
        header: (
          <span
            title={`${c.code ? `${c.code}. ` : ''}${c.label} — ${c.unavailable ?? c.description}`}
            className="cursor-help whitespace-nowrap underline decoration-dotted decoration-subtle underline-offset-2"
          >
            {c.code ? <span className="me-1 text-[10px] text-subtle">{c.code}</span> : null}
            {criterionShort(c)}
          </span>
        ),
        align: 'center',
        mobileLabel: criterionShort(c),
        // Birinchi bosishda muammolilar tepada.
        sortFirst: 'desc',
        sortValue: (r) => cellSortValue(r.cells[c.key]),
        cell: (r) => <Cell cell={r.cells[c.key]} />,
      }),
    ),
  ];

  return (
    <DataTable
      columns={columns}
      rows={data?.people ?? []}
      rowKey={(r) => r.id}
      loading={loading && !data}
      error={error}
      emptyTitle="Guruhda talaba yo‘q"
      fill
      dense
    />
  );
}
