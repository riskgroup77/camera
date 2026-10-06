import type { ReactNode } from 'react';
import { DataTable, cn, type DataTableColumn } from '../../ui';
import {
  TONE_TEXT,
  criterionShort,
  type GroupSumCell,
  type GroupsCriteria,
  type GroupsCriteriaRow,
} from '../../lib/groupCriteriaApi';

/**
 * Nazorat → "Kriteriyalar bo'yicha": har guruh qatorida har kriteriya bo'yicha
 * to'liq son (ustunma-ustun). Davomat — "kelgan / ro'yxatdan o'tgan";
 * boshqalari — holatlar soni. Guruh qatori bosilsa — o'sha guruhning
 * talabalar bo'yicha kriteriyalari ochiladi.
 */

const SEVERITY: Record<GroupSumCell['tone'], number> = { danger: 3, warning: 2, neutral: 1, success: 0 };

/** Saralash: avval muammolisi, so'ng soni kattasi; "8/12" — 8. */
export function sumSortValue(cell: GroupSumCell | undefined): number {
  if (!cell || cell.value === '—') return -1;
  const first = /\d+(?:[.,]\d+)?/.exec(cell.value);
  const number = first ? Number.parseFloat(first[0].replace(',', '.')) : 0;
  return SEVERITY[cell.tone] * 100_000 + number;
}

function Hint({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span title={text} className="cursor-help underline decoration-dotted decoration-subtle underline-offset-2">
      {children}
    </span>
  );
}

function SumCell({ cell }: { cell: GroupSumCell | undefined }) {
  if (!cell) return <span className="text-subtle">—</span>;
  return (
    <span
      title={cell.title}
      className={cn('whitespace-nowrap tabular-nums', cell.value === '—' ? 'text-subtle' : TONE_TEXT[cell.tone], cell.tone !== 'neutral' && 'font-semibold')}
    >
      {cell.value}
    </span>
  );
}

export default function GroupsCriteriaTable({
  data,
  rows,
  loading,
  error,
  onOpen,
}: {
  data: GroupsCriteria | null;
  /** Filtrlangan qatorlar (qidiruv, kurs). */
  rows: GroupsCriteriaRow[];
  loading: boolean;
  error: string | null;
  onOpen: (group: string) => void;
}) {
  const columns: DataTableColumn<GroupsCriteriaRow>[] = [
    { key: 'name', header: 'Guruh', sortValue: (r) => r.name, cell: (r) => <b>{r.name}</b> },
    { key: 'course', header: 'Kurs', sortValue: (r) => r.course ?? 0, cell: (r) => r.course ?? '—', align: 'center' },
    {
      key: 'total',
      header: <Hint text="Guruhdagi barcha faol talabalar">Jami</Hint>,
      sortValue: (r) => r.total,
      sortFirst: 'desc',
      align: 'right',
      cell: (r) => <span className="tabular-nums">{r.total}</span>,
    },
    {
      key: 'enrolled',
      header: <Hint text="Yuzi bazada bor (/royxatdan-otish orqali o‘tgan) — kamera taniydi">Ro‘yxatdan o‘tgan</Hint>,
      sortValue: (r) => r.enrolled,
      align: 'right',
      cell: (r) => <span className="tabular-nums">{r.enrolled}</span>,
    },
    ...(data?.criteria ?? []).map<DataTableColumn<GroupsCriteriaRow>>((c) => ({
      key: c.key,
      header: <Hint text={`${c.code ? `${c.code}. ` : ''}${c.label}${c.description ? ` — ${c.description}` : ''}`}>{criterionShort(c)}</Hint>,
      sortValue: (r) => sumSortValue(r.cells[c.key]),
      sortFirst: 'desc',
      align: 'right',
      cell: (r) => <SumCell cell={r.cells[c.key]} />,
    })),
  ];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(r) => r.name}
      onRowClick={(r) => onOpen(r.name)}
      loading={loading && !data}
      error={error}
      emptyTitle="Guruh topilmadi"
      fill
      dense
      defaultSort={{ key: 'total', dir: 'desc' }}
    />
  );
}
