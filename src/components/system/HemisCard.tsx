import { useState } from 'react';
import { DatabaseZap, PlugZap, RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { integrationsApi, type EntityStats, type HemisStatus, type SyncStats } from '../../lib/integrationsApi';
import { relativeTime } from '../../lib/uzDate';
import { Button, IntelPanel, MicroLabel, StatusLamp, useToast, type IntelStatus } from '../../ui';
import { useLiveResource } from '../situation/useLiveResource';

const STAT_KEYS = ['faculties', 'departments', 'groups', 'students', 'employees', 'schedule'] as const satisfies readonly (keyof SyncStats)[];
const STAT_LABEL: Record<(typeof STAT_KEYS)[number], string> = {
  faculties: 'Fakultetlar',
  departments: 'Kafedralar',
  groups: 'Guruhlar',
  students: 'Talabalar',
  employees: 'Xodimlar',
  schedule: 'Darslar',
};

const RUN_LABEL: Record<string, string> = {
  ishlamoqda: 'ishlamoqda',
  muvaffaqiyatli: 'muvaffaqiyatli',
  xato: 'xato',
};

/** HEMIS integratsiyasi: oxirgi sinxronlash, xato sababi, qo'lda ishga tushirish.
 *  Talabalar, xodimlar, tuzilma va dars jadvali shu yerdan keladi. */
export function HemisCard({ tick }: { tick: number }) {
  const { token } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<'sync' | 'test' | null>(null);
  const [nonce, setNonce] = useState(0);
  const status = useLiveResource('hemis-status', () => integrationsApi.hemisStatus(token), tick + nonce);
  const data: HemisStatus | null = status.data;

  async function run(kind: 'sync' | 'test') {
    setBusy(kind);
    try {
      if (kind === 'sync') {
        await integrationsApi.hemisSync(token);
        toast.success('HEMIS sinxronlash boshlandi — bir necha daqiqa oladi');
      } else {
        const res = await integrationsApi.hemisTest(token);
        const bad = Object.entries(res.entities).filter(([, e]) => !e.ok).map(([name]) => name);
        if (res.ok && bad.length === 0) toast.success('HEMIS bilan aloqa joyida');
        else toast.error(res.error ?? `Javob bermadi: ${bad.join(', ')}`);
      }
      setNonce((n) => n + 1);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setBusy(null);
    }
  }

  const last = data?.running ?? data?.lastRun ?? null;
  const lamp: IntelStatus = !data ? 'idle' : !data.configured ? 'idle' : data.running ? 'warn' : last?.status === 'xato' ? 'alert' : 'ok';

  return (
    <IntelPanel
      title="HEMIS integratsiyasi"
      right={data ? <StatusLamp status={lamp} label={!data.configured ? 'sozlanmagan' : data.running ? 'ishlamoqda' : last?.status === 'xato' ? 'xato' : 'joyida'} /> : undefined}
      bodyClassName="flex flex-col gap-2 p-3 text-[13px]"
    >
      {status.error && !data && <p className="text-danger">{status.error}</p>}
      {data && !data.configured && <p className="text-muted">HEMIS_BASE_URL va HEMIS_API_TOKEN sozlanmagan.</p>}
      {data?.configured && (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted">Oxirgi muvaffaqiyatli</dt>
            <dd>{data.lastSuccessAt ? relativeTime(data.lastSuccessAt) : '—'}</dd>
            <dt className="text-muted">Oxirgi urinish</dt>
            <dd>
              {last?.startedAt ? relativeTime(last.startedAt) : '—'}
              {last && <span className="text-muted"> · {RUN_LABEL[last.status] ?? last.status}</span>}
              {last?.durationSeconds != null && <span className="text-muted"> · {Math.round(last.durationSeconds)} s</span>}
            </dd>
            <dt className="text-muted">Jadval</dt>
            <dd>har {data.syncIntervalHours} soatda</dd>
          </dl>
          {last?.status === 'xato' && last.error && (
            <p className="border border-danger/40 bg-danger-soft px-2 py-1 text-[12px] text-fg">{last.error}</p>
          )}
          {last?.stats && (
            <div className="grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-3">
              {STAT_KEYS.filter((key) => last.stats?.[key]).map((key) => {
                const entity = last.stats?.[key] as EntityStats;
                return (
                  <div key={key} className="bg-surface px-2 py-1">
                    <MicroLabel className="block">{STAT_LABEL[key]}</MicroLabel>
                    <span className="intel-code text-[13px] font-semibold text-fg">{entity.fetched}</span>
                    <span className="text-[11px] text-muted">
                      {entity.created ? ` +${entity.created}` : ''}
                      {entity.updated ? ` ~${entity.updated}` : ''}
                      {entity.errors ? ` · ${entity.errors} xato` : ''}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" icon={RefreshCw} onClick={() => run('sync')} disabled={busy !== null || !!data.running}>
              {busy === 'sync' ? 'Boshlanmoqda…' : 'Hozir sinxronlash'}
            </Button>
            <Button size="sm" variant="ghost" icon={PlugZap} onClick={() => run('test')} disabled={busy !== null}>
              Aloqani tekshirish
            </Button>
          </div>
        </>
      )}
      {!data && !status.error && (
        <span className="inline-flex items-center gap-2 text-muted">
          <DatabaseZap size={14} aria-hidden="true" /> Yuklanmoqda…
        </span>
      )}
    </IntelPanel>
  );
}
