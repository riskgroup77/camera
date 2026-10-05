import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../../lib/apiClient';
import {
  getPeopleStatus,
  type PeopleStatusKey,
  type StatusPeopleQuery,
  type StatusPeoplePage,
  type StatusPerson,
} from '../../lib/situationApi';
import { Button, DataTable, StatusBadge, cn, type DataTableColumn } from '../../ui';

/**
 * Holat bo'yicha odamlar — butun institut yoki filtrlangan bo'lak.
 * Sahifalab (server), `refreshKey` o'zgarganda qayta yuklanadi (jonli).
 */

const PAGE_SIZE = 50;

export default function StatusPeopleTable({
  query,
  status,
  refreshKey = 0,
  onLoaded,
  maxHeight,
  fill = false,
}: {
  query: Omit<StatusPeopleQuery, 'status' | 'page' | 'pageSize'>;
  status: PeopleStatusKey;
  refreshKey?: number;
  onLoaded?: (page: StatusPeoplePage) => void;
  maxHeight?: string;
  /** Ota balandligini to'ldiradi va ichida aylanadi. */
  fill?: boolean;
}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<StatusPeoplePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(query) + status;

  useEffect(() => setPage(1), [key]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getPeopleStatus({ ...query, status, page, pageSize: PAGE_SIZE }, { signal: controller.signal })
      .then((result) => {
        setData(result);
        setError(null);
        onLoaded?.(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      })
      .finally(() => !controller.signal.aborted && setLoading(false));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` query+status ni qamraydi
  }, [key, page, refreshKey]);

  const offset = (page - 1) * PAGE_SIZE;
  const columns: DataTableColumn<StatusPerson>[] = [
    { key: 'n', header: '№', width: '3rem', cell: (_row, index) => offset + index + 1, mono: true },
    {
      key: 'name',
      header: 'F.I.Sh.',
      cell: (row) => (
        <Link to={`/shaxs/${encodeURIComponent(row.id)}`} className="font-medium text-fg hover:text-primary">
          {row.fullName}
        </Link>
      ),
    },
    ...(query.type === 'xodim'
      ? [
          { key: 'position', header: 'Lavozim', cell: (row: StatusPerson) => row.position || '—' },
          { key: 'unit', header: 'Bo‘linma', cell: (row: StatusPerson) => row.unit ?? row.group ?? '—', hideOnMobile: true },
        ]
      : [
          { key: 'group', header: 'Guruh', cell: (row: StatusPerson) => row.group || '—' },
          { key: 'faculty', header: 'Fakultet', cell: (row: StatusPerson) => row.faculty ?? '—', hideOnMobile: true },
        ]),
    { key: 'status', header: 'Holat', cell: (row) => <StatusBadge status={row.status === 'malumot_yoq' ? 'nomalum' : row.status} /> },
    { key: 'checkIn', header: 'Kelgan', cell: (row) => row.checkIn ?? '—', mono: true },
    {
      key: 'face',
      header: 'Yuz',
      cell: (row) =>
        row.biometricsStatus === 'tasdiqlangan' ? (
          <span className="text-[12px] text-success">bazada</span>
        ) : (
          <span className="text-[12px] font-semibold text-danger">yo‘q</span>
        ),
    },
  ];

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  return (
    <div className={cn('flex min-h-0 flex-col gap-2', fill && 'h-full')}>
      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(row) => row.id}
        loading={loading && !data}
        error={error}
        emptyTitle="Hech kim yo‘q"
        maxHeight={maxHeight}
        fill={fill}
        className={fill ? 'min-h-0 flex-1' : undefined}
        dense
      />
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 text-[12px] text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} / {data.total}
          </span>
          <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Oldingi
          </Button>
          <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Keyingi
          </Button>
        </div>
      )}
    </div>
  );
}
