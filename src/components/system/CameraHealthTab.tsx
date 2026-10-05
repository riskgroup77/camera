import { useMemo, useState } from 'react';
import { Camera, CameraOff, Film, Gauge, MonitorPlay, VideoOff } from 'lucide-react';
import {
  Badge,
  ButtonLink,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  SearchInput,
  Skeleton,
  StatTile,
  StatusDot,
  cn,
  focusRing,
  type DataTableColumn,
  type Tone,
} from '../../ui';
import { RAG_TEXT } from '../../ui/rag';
import {
  HEALTH_FILTERS,
  STATE_META,
  filterCameras,
  filterCounts,
  formatDuration,
  formatUptime,
  getCameraHealth,
  getCameraOutages,
  locationLabel,
  uptimeRag,
  type CameraHealthRow,
  type HealthFilter,
} from '../../lib/cameraHealthApi';
import { relativeTime } from '../../lib/uzDate';
import { useLiveResource } from '../situation/useLiveResource';

interface Props {
  tick: number;
}

function sinceSeconds(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.max(0, ms / 1000) : null;
}

function Uptime({ value }: { value: number }) {
  return <span className={cn('intel-code', RAG_TEXT[uptimeRag(value)])}>{formatUptime(value)}</span>;
}

/** Jonli/yozuv yo'li chirog'i. null — MediaMTX javob bermadi (noma'lum). */
function PathLamp({ ready, label, title }: { ready: boolean | null; label: string; title?: string }) {
  const tone: Tone = ready === null ? 'neutral' : ready ? 'success' : 'danger';
  const state = ready === null ? "noma‘lum" : ready ? 'tayyor' : "yo‘q";
  return (
    <span className="inline-flex items-center gap-1 text-[12px] text-muted" title={title ?? `${label}: ${state}`}>
      <StatusDot tone={tone} label={`${label}: ${state}`} />
      {label}
    </span>
  );
}

const COLUMNS: DataTableColumn<CameraHealthRow>[] = [
  {
    key: 'status',
    header: 'Holat',
    width: '7.5rem',
    cell: (row) => (
      <Badge tone={STATE_META[row.status].tone} dot>
        {STATE_META[row.status].label}
      </Badge>
    ),
    // Eng yomoni birinchi: oflayn -> tasvirsiz -> onlayn.
    sortValue: (row) => (row.status === 'offline' ? 0 : row.status === 'no_video' ? 1 : 2),
  },
  {
    key: 'name',
    header: 'Kamera',
    cell: (row) => (
      <div className="min-w-0">
        <p className="truncate font-medium text-fg">{row.name}</p>
        <p className="intel-code truncate text-[11px] text-subtle">{row.ip}</p>
      </div>
    ),
    sortValue: (row) => row.name,
  },
  {
    key: 'joy',
    header: 'Joy',
    cell: (row) => <span className="text-muted">{locationLabel(row)}</span>,
    sortValue: (row) => `${row.building ?? ''} ${String(row.floor ?? '').padStart(2, '0')}`,
    hideOnMobile: true,
  },
  {
    key: 'uptimeDay',
    header: '24 soat',
    align: 'right',
    width: '5.5rem',
    cell: (row) => <Uptime value={row.uptimeDay} />,
    sortValue: (row) => row.uptimeDay,
  },
  {
    key: 'uptimeWeek',
    header: '7 kun',
    align: 'right',
    width: '5.5rem',
    cell: (row) => <Uptime value={row.uptimeWeek} />,
    sortValue: (row) => row.uptimeWeek,
  },
  {
    key: 'offlineSince',
    header: 'Oflayn',
    align: 'right',
    width: '7rem',
    cell: (row) => {
      const s = sinceSeconds(row.offlineSince);
      return s === null ? <span className="text-subtle">—</span> : <span className="text-danger" title={row.offlineSince ?? undefined}>{formatDuration(s)}</span>;
    },
    sortValue: (row) => sinceSeconds(row.offlineSince) ?? -1,
    sortFirst: 'desc',
  },
  {
    key: 'outagesWeek',
    header: 'Uzilish',
    align: 'right',
    width: '5rem',
    cell: (row) => row.outagesWeek,
    sortValue: (row) => row.outagesWeek,
    sortFirst: 'desc',
  },
  {
    key: 'oqim',
    header: 'Oqim',
    width: '8.5rem',
    cell: (row) => (
      <span className="inline-flex gap-2">
        <PathLamp ready={row.liveReady} label="Jonli" />
      </span>
    ),
    sortValue: (row) => (row.liveReady ? 1 : 0),
  },
  {
    key: 'ai',
    header: 'AI',
    align: 'right',
    width: '7.5rem',
    cell: (row) =>
      row.aiLastAnalyzedAt ? (
        <span className="text-muted" title={row.aiStream ? `Oqim: ${row.aiStream}` : undefined}>
          {relativeTime(row.aiLastAnalyzedAt)}
        </span>
      ) : (
        <span className="text-subtle">—</span>
      ),
    sortValue: (row) => (row.aiLastAnalyzedAt ? new Date(row.aiLastAnalyzedAt).getTime() : 0),
    hideOnMobile: true,
  },
];

/** "Kameralar" tabi — har bir kameraning salomatligi (Genetec Health
 *  Monitor uslubida): holat, uptime, uzilishlar, oqim/yozuv, AI. */
export function CameraHealthTab({ tick }: Props) {
  const res = useLiveResource('kamera-salomatligi', (signal) => getCameraHealth({ signal }), tick);
  const [filter, setFilter] = useState<HealthFilter>('hammasi');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const cameras = useMemo(() => res.data?.cameras ?? [], [res.data]);
  const counts = useMemo(() => filterCounts(cameras), [cameras]);
  const rows = useMemo(() => filterCameras(cameras, filter, query), [cameras, filter, query]);
  const selected = cameras.find((c) => c.id === selectedId) ?? null;
  const s = res.data?.summary;

  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-5">
        <StatTile label="Jami" value={s?.total ?? 0} icon={Camera} loading={res.loading} />
        <StatTile label="Onlayn" value={s?.online ?? 0} icon={MonitorPlay} tone="success" loading={res.loading} />
        <StatTile
          label="Oflayn"
          value={s?.offline ?? 0}
          icon={CameraOff}
          tone={s && s.offline > 0 ? 'danger' : 'neutral'}
          loading={res.loading}
          onClick={() => setFilter('oflayn')}
        />
        <StatTile
          label="Tasvirsiz"
          value={s?.noVideo ?? 0}
          icon={VideoOff}
          tone={s && s.noVideo > 0 ? 'warning' : 'neutral'}
          loading={res.loading}
          onClick={() => setFilter('tasvirsiz')}
        />
        <StatTile
          label="Uptime 24 soat"
          value={formatUptime(s?.avgUptimeDay)}
          icon={Gauge}
          rag={s?.avgUptimeDay != null ? uptimeRag(s.avgUptimeDay) : null}
          animate={false}
          loading={res.loading}
        />
      </div>

      {res.data && !res.data.mediamtxReachable && (
        <p role="status" className="border border-warning/40 bg-warning-soft px-3 py-2 text-[13px] text-fg">
          MediaMTX javob bermadi — jonli oqim holati noma‘lum.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtr">
          {HEALTH_FILTERS.map((f) => {
            const active = filter === f.id;
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(f.id)}
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 rounded-[2px] border px-2.5 text-[13px] transition-colors',
                  active ? 'border-primary bg-primary-soft text-primary' : 'border-border bg-surface text-muted hover:border-border-strong',
                  focusRing,
                )}
              >
                {f.label}
                <span className="intel-code text-[11px] opacity-80">{counts[f.id]}</span>
              </button>
            );
          })}
        </div>
        <SearchInput value={query} onChange={setQuery} placeholder="Nom, IP, bino" size="sm" className="ml-auto w-full sm:w-56" />
      </div>

      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.id}
        onRowClick={(row) => setSelectedId(row.id)}
        selectedKey={selectedId}
        rowTone={(row) => (row.status === 'online' ? null : STATE_META[row.status].tone)}
        defaultSort={{ key: 'status', dir: 'asc' }}
        loading={res.loading}
        error={res.data ? null : res.error}
        onRetry={res.reload}
        emptyTitle={cameras.length ? 'Mos kamera yo‘q' : 'Faol kamera yo‘q'}
        ariaLabel="Kameralar salomatligi"
        dense
      />

      <CameraOutageDrawer camera={selected} onClose={() => setSelectedId(null)} />
    </div>
  );
}

function CameraOutageDrawer({ camera, onClose }: { camera: CameraHealthRow | null; onClose: () => void }) {
  const id = camera?.id ?? null;
  const history = useLiveResource(id ? `uzilishlar-${id}` : null, (signal) => getCameraOutages(id ?? '', 30, { signal }), 0);

  return (
    <Drawer
      open={camera !== null}
      onClose={onClose}
      title={camera?.name}
      subtitle={camera ? `${camera.ip} · ${locationLabel(camera)}` : undefined}
      footer={
        camera && (
          <div className="flex flex-wrap gap-2">
            <ButtonLink to={`/videodevor?kamera=${encodeURIComponent(camera.id)}`} icon={Film} size="sm">
              Jonli
            </ButtonLink>
          </div>
        )
      }
    >
      {camera && (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
            <dt className="text-muted">Holat</dt>
            <dd>
              <Badge tone={STATE_META[camera.status].tone} dot>
                {STATE_META[camera.status].label}
              </Badge>
            </dd>
            <dt className="text-muted">Uptime 24 soat / 7 kun</dt>
            <dd>
              <Uptime value={camera.uptimeDay} /> / <Uptime value={camera.uptimeWeek} />
            </dd>
            <dt className="text-muted">Oxirgi javob</dt>
            <dd>{camera.lastSeenAt ? relativeTime(camera.lastSeenAt) : '—'}</dd>
            <dt className="text-muted">Oxirgi kadr</dt>
            <dd>{camera.lastFrameAt ? relativeTime(camera.lastFrameAt) : '—'}</dd>
            <dt className="text-muted">AI tahlili</dt>
            <dd>
              {camera.aiLastAnalyzedAt ? relativeTime(camera.aiLastAnalyzedAt) : '—'}
              {camera.aiStream && <span className="text-subtle"> · {camera.aiStream}</span>}
            </dd>
          </dl>

          <section>
            <h3 className="intel-micro mb-2">Uzilishlar · 30 kun</h3>
            {history.loading ? (
              <Skeleton className="h-24 w-full" />
            ) : history.error ? (
              <ErrorState message={history.error} onRetry={history.reload} />
            ) : !history.data?.items.length ? (
              <EmptyState title="Uzilish bo‘lmagan" compact />
            ) : (
              <ul className="divide-y divide-border border-y border-border">
                {history.data.items.map((o) => (
                  <li key={o.id} className="flex items-center gap-3 px-1 py-1.5 text-[13px]">
                    <StatusDot tone={o.endedAt ? 'neutral' : 'danger'} pulse={!o.endedAt} />
                    <span className="intel-code min-w-0 flex-1 truncate text-fg">
                      {new Date(o.startedAt).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Tashkent' })}
                    </span>
                    <span className={cn('intel-code shrink-0', o.endedAt ? 'text-muted' : 'text-danger')}>
                      {o.endedAt ? formatDuration(o.durationSeconds) : `davom etmoqda · ${formatDuration(o.durationSeconds)}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
