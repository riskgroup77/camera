import { useCallback, useEffect, useState } from 'react';
import { CirclePlay, CircleStop } from 'lucide-react';
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  DatePicker,
  IntelPanel,
  MicroLabel,
  ProgressBar,
  Readout,
  useToast,
  type DataTableColumn,
} from '../../ui';
import { Notice } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { todayInTashkent } from '../../lib/uzDate';
import {
  JOB_KIND_LABELS,
  JOB_STATUS_LABELS,
  RUN_STATUS_META,
  clockOf,
  etaMinutes,
  isRunActive,
  runProgressText,
  videoAnalysisApi,
  type AnalysisRun,
  type AnalysisStatus,
  type RunDetail,
} from '../../lib/videoAnalysisApi';

function dateTime(iso: string | null): string {
  if (!iso) return '—';
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)} ${clockOf(iso)}`;
}

function yesterday(): string {
  const d = new Date(`${todayInTashkent()}T12:00:00`);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** Tahlil ishlari: joriy jarayon, qo'lda ishga tushirish, tarix. */
export default function RunsTab({
  status,
  canManage,
  onChanged,
}: {
  status: AnalysisStatus | null;
  canManage: boolean;
  onChanged: () => void;
}) {
  const { token } = useAuth();
  const toast = useToast();
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState(yesterday);
  const [starting, setStarting] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const current = status?.current ?? null;

  const load = useCallback(async () => {
    try {
      setRuns(await videoAnalysisApi.runs(token));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tahlillar ro'yxatini yuklab bo'lmadi");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load, current?.jobsDone, current?.status]);

  useEffect(() => {
    if (!current) return;
    videoAnalysisApi.run(current.id, token).then(setDetail, () => setDetail(null));
  }, [current, token]);

  async function start() {
    setStarting(true);
    try {
      await videoAnalysisApi.start(day, token);
      toast.success(`${day} kuni tahlil navbatga qo'yildi`);
      onChanged();
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Ishga tushirib bo'lmadi");
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!current) return;
    await videoAnalysisApi.cancel(current.id, token);
    toast.success("Tahlil to'xtatilmoqda");
    setConfirmCancel(false);
    onChanged();
  }

  const columns: DataTableColumn<AnalysisRun>[] = [
    { key: 'day', header: 'Kun', cell: (r) => <span className="font-medium tabular-nums">{r.day}</span> },
    {
      key: 'status',
      header: 'Holat',
      cell: (r) => (
        <Badge tone={RUN_STATUS_META[r.status].tone} dot>
          {RUN_STATUS_META[r.status].label}
        </Badge>
      ),
    },
    { key: 'jobs', header: 'Vazifalar', align: 'right', cell: (r) => `${r.jobsDone}/${r.jobsTotal}` },
    { key: 'frames', header: 'Kadrlar', align: 'right', hideOnMobile: true, cell: (r) => r.framesAnalyzed.toLocaleString('ru-RU') },
    { key: 'obs', header: 'Tanilgan', align: 'right', hideOnMobile: true, cell: (r) => r.observations.toLocaleString('ru-RU') },
    { key: 'time', header: 'Boshlandi', hideOnMobile: true, cell: (r) => dateTime(r.startedAt) },
    { key: 'end', header: 'Tugadi', hideOnMobile: true, cell: (r) => dateTime(r.finishedAt) },
    {
      key: 'note',
      header: 'Izoh',
      hideOnMobile: true,
      cell: (r) => (
        <span className="text-[12px] text-muted">
          {r.error ?? (typeof r.stats?.izoh === 'string' ? r.stats.izoh : r.triggeredBy === 'qolda' ? "qo'lda" : '')}
        </span>
      ),
    },
  ];

  const eta = current ? etaMinutes(current) : null;
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {status?.mode === 'realtime' && (
        <Notice tone="warning">Server real vaqt rejimida (ANALYSIS_MODE=realtime) — kunlik tahlil avtomatik ishlamaydi.</Notice>
      )}
      <IntelPanel
        title="Joriy tahlil"
        right={current ? <Badge tone={RUN_STATUS_META[current.status].tone}>{RUN_STATUS_META[current.status].label}</Badge> : undefined}
      >
        <div className="flex flex-col gap-3 p-3">
          {current ? (
            <>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <Readout label="Kun" value={current.day} />
                <Readout label="Oyna" value={`${clockOf(current.windowStart)}–${clockOf(current.windowEnd)}`} />
                <Readout label="Jarayon" value={runProgressText(current)} />
                <Readout label="Tanilgan yuzlar" value={current.observations.toLocaleString('ru-RU')} />
                {eta !== null && <Readout label="Taxminan qoldi" value={eta >= 60 ? `${Math.floor(eta / 60)} soat ${eta % 60} daq` : `${eta} daq`} />}
              </div>
              <ProgressBar value={Math.round(current.progress * 100)} showValue ariaLabel="Tahlil jarayoni" />
              {detail && detail.jobs.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {detail.jobs.map((j) => (
                    <MicroLabel key={`${j.kind}-${j.status}`}>
                      {JOB_KIND_LABELS[j.kind] ?? j.kind}: {j.count} {JOB_STATUS_LABELS[j.status] ?? j.status}
                    </MicroLabel>
                  ))}
                </div>
              )}
              {canManage && isRunActive(current) && (
                <div>
                  <Button size="sm" variant="danger" icon={CircleStop} onClick={() => setConfirmCancel(true)}>
                    To'xtatish
                  </Button>
                </div>
              )}
            </>
          ) : (
            <p className="text-[13px] text-muted">
              Hozir tahlil ketmayapti.{' '}
              {status?.nextRunAt ? `Keyingisi: ${dateTime(status.nextRunAt)} (kun yozuvlari ${status.dayStart}–${status.startTime}).` : ''}
            </p>
          )}
          {canManage && !isRunActive(current) && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <DatePicker value={day} onChange={setDay} quick stepper ariaLabel="Tahlil kuni" />
              <Button size="sm" variant="primary" icon={CirclePlay} loading={starting} onClick={() => void start()}>
                Shu kunni tahlil qilish
              </Button>
              <span className="text-[12px] text-muted">Kun qayta hisoblansa, avvalgi natijasi yangisi bilan almashtiriladi.</span>
            </div>
          )}
        </div>
      </IntelPanel>

      {detail && detail.errors.length > 0 && (
        <IntelPanel title="Muammoli vazifalar" right={<MicroLabel>{detail.errors.length} ta</MicroLabel>}>
          <ul className="divide-y divide-border">
            {detail.errors.slice(0, 12).map((e, i) => (
              <li key={i} className="px-3 py-2 text-[12px]">
                <span className="font-medium text-fg">{e.cameraName ?? 'Kamera'}</span>{' '}
                <span className="text-muted">
                  · {JOB_KIND_LABELS[e.kind] ?? e.kind} · {clockOf(e.startAt)} · {JOB_STATUS_LABELS[e.status] ?? e.status}
                </span>
                {e.error && <p className="truncate text-subtle" title={e.error}>{e.error}</p>}
              </li>
            ))}
          </ul>
        </IntelPanel>
      )}

      <IntelPanel title="Tahlillar tarixi">
        <DataTable
          columns={columns}
          rows={runs}
          rowKey={(r) => r.id}
          rowTone={(r) => (r.status === 'xato' ? 'danger' : r.status === 'bekor' ? 'warning' : null)}
          loading={loading && runs.length === 0}
          error={error}
          onRetry={() => void load()}
          emptyTitle="Hali tahlil bo'lmagan"
          emptyDescription={`Birinchi tahlil bugun ${status?.startTime ?? '20:00'} da avtomatik boshlanadi.`}
          ariaLabel="Tahlillar tarixi"
          maxHeight="none"
          dense
        />
      </IntelPanel>

      <ConfirmDialog
        open={confirmCancel}
        title="Tahlilni to'xtatish"
        message="Bajarilmagan vazifalar bekor qilinadi va kun natijalari hisoblanmaydi. Keyin kunni qayta ishga tushirish mumkin."
        confirmLabel="To'xtatish"
        onCancel={() => setConfirmCancel(false)}
        onConfirm={cancel}
      />
    </div>
  );
}
