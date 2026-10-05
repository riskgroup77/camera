import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { Button, CodeText, ConfirmDialog, IntelPanel, StatusLamp, formatNumber, rag, useToast } from '../../ui';
import type { LiveResource } from '../situation/useLiveResource';
import { MeasuredAt, Metric, Recommendation, ResourceBody, StatusLine } from './parts';
import { COVERAGE_RAG, type SystemStreamStatus } from './systemTypes';

/**
 * Video oqimlar (MediaMTX) — o'lchov bloki.
 *
 * Ro'yxatdan o'tgan oqimlar ULUSHI uchun chegara bor (hammasi bo'lishi
 * shart), shuning uchun svetofor bilan. Tugun soni — sanoq, betaraf.
 */
export function StreamsCard({ resource, canResync }: { resource: LiveResource<SystemStreamStatus>; canResync: boolean }) {
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);

  async function resync() {
    const res = await api.post<{ synced: number; failed: number }>('/api/system/resync-streams', {});
    setConfirm(false);
    toast.success(`${res.synced} ta oqim sinxronlandi${res.failed ? `, ${res.failed} ta xato` : ''}`);
    resource.reload();
  }

  return (
    <IntelPanel
      title="Video oqimlar"
      brackets={false}
      right={
        <span className="flex items-center gap-3">
          <MeasuredAt resource={resource} />
          {canResync && (
            <Button size="sm" variant="secondary" icon={RefreshCw} onClick={() => setConfirm(true)}>
              Qayta sinxronlash
            </Button>
          )}
        </span>
      }
    >
      <ResourceBody resource={resource}>
        {(data) => {
          const missing = Math.max(0, data.faolCameras - data.registeredStreams);
          const coverage = data.faolCameras > 0 ? (data.registeredStreams / data.faolCameras) * 100 : null;
          return (
            <div>
              <div className="grid grid-cols-2 gap-px border-b border-border bg-border">
                <Metric
                  label="Oqimlar"
                  value={`${formatNumber(data.registeredStreams)} / ${formatNumber(data.faolCameras)}`}
                  unit={coverage === null ? undefined : `${formatNumber(coverage, 0)}%`}
                  verdict={rag(coverage, COVERAGE_RAG)}
                  hint={missing > 0 ? `${missing} ta oqimsiz` : undefined}
                />
                {/* Tugun soni — sozlamaga bog'liq sanoq, yaxshi/yomoni yo'q. */}
                <Metric
                  label="Tugunlar"
                  value={data.shardingEnabled ? formatNumber(data.shardCount) : '1'}
                  unit={data.shardingEnabled ? 'shard' : 'tugun'}
                />
              </div>
              {/* Ro'yxat bo'sh bo'lsa ilgari bo'm-bo'sh ramka qolardi — sabab aytilmasdi. */}
              {data.shards.length === 0 ? (
                <StatusLine tone="danger">MediaMTX tugunlari topilmadi — oqimlar ishlamaydi</StatusLine>
              ) : (
                <ul className="divide-y divide-border border-b border-border">
                  {data.shards.map((shard) => (
                    <li key={shard.index} className="px-2.5 py-1.5 text-[13px]">
                      <div className="flex items-center gap-3">
                        <span className="min-w-0 flex-1 truncate text-fg">Tugun {shard.index + 1}</span>
                        <CodeText className="shrink-0 text-[12px] text-muted">
                          {formatNumber(shard.pathCount)} oqim · {formatNumber(shard.assignedCameras)} kamera
                        </CodeText>
                        <StatusLamp
                          className="shrink-0"
                          status={shard.reachable ? 'ok' : 'alert'}
                          label={shard.reachable ? 'Ishlayapti' : "Aloqa yo'q"}
                        />
                      </div>
                      {shard.error && <p className="mt-0.5 break-words text-xs text-danger">{shard.error}</p>}
                    </li>
                  ))}
                </ul>
              )}
              <Recommendation>{data.recommendation}</Recommendation>
            </div>
          );
        }}
      </ResourceBody>
      <ConfirmDialog
        open={confirm}
        tone="primary"
        title="Oqimlarni qayta sinxronlash"
        message="Barcha oqimlar qayta ro'yxatdan o'tadi. Videodevorda qisqa uzilish bo'ladi."
        confirmLabel="Sinxronlash"
        onCancel={() => setConfirm(false)}
        onConfirm={resync}
      />
    </IntelPanel>
  );
}
