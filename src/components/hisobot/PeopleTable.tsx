import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Video } from 'lucide-react';
import { Avatar, CodeText, DataTable, EmptyState, cn, type DataTableColumn, type SortState } from '../../ui';
import { RAG_TEXT, RATE_RAG, rag } from '../../ui/rag';
import { RagChip } from './board';
import { formatCell, type HisobotColumn, type HisobotPerson, type HisobotReport } from '../../lib/hisobotApi';

/**
 * Batafsil ro'yxat: bitta odam — bitta qator.
 *
 * Foizli ustunlar svetofor bilan chiqadi, qolganlari — oddiy raqam.
 * Qator bosilganda shaxs kartasi ochiladi.
 */

/** Har odam qatoridagi video dalillar soni (backend: hisobot.EVIDENCE_COLUMN). */
const EVIDENCE_KEY = 'dalil';

/** Ustun foizmi — faqat shundagina hukm chiqaramiz. */
function isRateColumn(column: HisobotColumn) {
  return column.unit === '%' && column.better === 'up';
}

function numberOf(value: string | number | null | undefined): number | null {
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(',', '.').replace(/[^\d.-]/g, ''));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export default function PeopleTable({ data }: { data: HisobotReport }) {
  const navigate = useNavigate();
  const body = data.report;
  const [sort, setSort] = useState<SortState | null>(
    body.sort_key ? { key: body.sort_key, dir: body.worst_desc ? 'desc' : 'asc' } : null,
  );

  if (body.empty) {
    return <EmptyState title={body.empty.title} description={body.empty.description} />;
  }

  const columns: DataTableColumn<HisobotPerson>[] = [
    {
      key: 'full_name',
      header: 'F.I.Sh.',
      sortValue: (person) => person.full_name,
      cell: (person) => (
        <span className="flex min-w-0 items-center gap-2">
          <Avatar name={person.full_name} src={person.photo_url} size="sm" />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-fg">{person.full_name}</span>
            <span className="block truncate text-[11px] text-muted">{person.unit}</span>
          </span>
        </span>
      ),
    },
    ...body.columns.map((column): DataTableColumn<HisobotPerson> => {
      const rateColumn = isRateColumn(column);
      return {
        key: column.key,
        header: column.label,
        align: column.type === 'text' ? 'left' : 'right',
        sortValue: (person) => numberOf(person.values[column.key]) ?? -Infinity,
        cell: (person) => {
          const raw = person.values[column.key];
          const text = formatCell(raw, column.unit);
          if (column.key === EVIDENCE_KEY) {
            // Video dalil (2 daqiqalik klip) — odam kartasida ko'riladi; qator bosilganda ochiladi.
            if (!numberOf(raw)) return <span className="text-muted">—</span>;
            return (
              <span className="flex items-center justify-end gap-1 text-primary" title="Video dalillar — odam kartasida">
                <Video size={13} aria-hidden="true" />
                <CodeText className="text-[13px] font-medium">{text}</CodeText>
              </span>
            );
          }
          if (!rateColumn) return <CodeText className="text-[13px]">{text}</CodeText>;
          const tone = rag(numberOf(raw), RATE_RAG);
          return (
            <span className="flex items-center justify-end gap-1.5">
              <CodeText className={cn('text-[13px] font-semibold', RAG_TEXT[tone])}>{text}</CodeText>
              <RagChip tone={tone} />
            </span>
          );
        },
      };
    }),
  ];

  return (
    <DataTable
      rows={body.people}
      columns={columns}
      rowKey={(person) => person.id}
      sort={sort}
      onSortChange={setSort}
      onRowClick={(person) => navigate(`/shaxs/${person.id}`)}
      emptyTitle="Tanlovga mos odam topilmadi"
      dense
    />
  );
}
