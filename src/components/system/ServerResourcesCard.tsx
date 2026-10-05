import { CodeText, IntelPanel, MicroLabel, RAG_SOLID, RAG_TEXT, cn, formatNumber, rag } from '../../ui';
import type { LiveResource } from '../situation/useLiveResource';
import { MeasuredAt, Metric, ResourceBody, StatusLine } from './parts';
import {
  RESOURCE_DANGER_AT,
  RESOURCE_RAG,
  RESOURCE_TONE_LABEL as TONE_LABEL,
  resourceTone,
  type SystemResources,
} from './systemTypes';

const GAUGES = [
  { key: 'cpu', label: 'Protsessor' },
  { key: 'ram', label: 'Xotira' },
  { key: 'disk', label: 'Disk' },
] as const;

/**
 * Server resurslari — o'lchov bloki.
 *
 * CPU/RAM/disk uchun chegara HAQIQATAN mavjud (60% / 80%), shuning uchun
 * har biri svetofor hukmi bilan chiqadi. ffmpeg jarayonlari va oqim
 * o'quvchilari — shunchaki sanoq: server hajmiga qarab ko'p bo'lgani
 * yomon emas, shuning uchun betaraf qoladi.
 */
export function ServerResourcesCard({ resource }: { resource: LiveResource<SystemResources> }) {
  return (
    <IntelPanel title="Server resurslari" right={<MeasuredAt resource={resource} />}>
      <ResourceBody resource={resource}>
        {(data) => {
          const alerts = data.alerts.filter((a) => a.metric !== 'security');
          // Chegara resourceTone bilan bir xil bo'lishi shart — avval bu yerda 80 qo'lda yozilgandi.
          const hot = GAUGES.filter((g) => resourceTone(data[g.key]) === 'danger');
          return (
            <div>
              {/* O'lchagich shkalasi: qiymat, birlik (%), hukm harfi va ustun. */}
              <ul className="divide-y divide-border border-b border-border">
                {GAUGES.map((gauge) => {
                  const value = data[gauge.key];
                  const verdict = rag(value, RESOURCE_RAG);
                  const tone = resourceTone(value);
                  return (
                    <li key={gauge.key} className="flex items-center gap-3 px-2.5 py-1.5">
                      <MicroLabel className="w-[92px] shrink-0">{gauge.label}</MicroLabel>
                      <span className="relative h-1.5 min-w-0 flex-1 bg-surface-2" aria-hidden="true">
                        <span
                          className={cn('absolute inset-y-0 start-0', RAG_SOLID[verdict])}
                          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                        />
                      </span>
                      <CodeText className={cn('w-14 shrink-0 text-end text-[13px] font-semibold', RAG_TEXT[verdict])}>
                        {formatNumber(value, 1)}
                      </CodeText>
                      <MicroLabel className="!text-subtle">%</MicroLabel>
                      <MicroLabel className={cn('w-[112px] shrink-0 text-end', RAG_TEXT[verdict])}>
                        {TONE_LABEL[tone]}
                      </MicroLabel>
                    </li>
                  );
                })}
              </ul>
              <div className="grid grid-cols-2 gap-px border-b border-border bg-border">
                {/* Chegarasi yo'q sanoqlar — svetoforsiz. */}
                <Metric label="ffmpeg" value={formatNumber(data.ffmpegProcessCount)} unit="ta" />
                <Metric label="Oqim o'quvchilari" value={formatNumber(data.streamReaderCount)} unit="ta" />
              </div>
              {alerts.length > 0 ? (
                <div className="divide-y divide-border">
                  {alerts.map((alert) => (
                    <StatusLine key={`${alert.metric}-${alert.message}`} tone={alert.level === 'critical' ? 'danger' : 'warning'}>
                      {alert.message}
                    </StatusLine>
                  ))}
                </div>
              ) : hot.length > 0 ? (
                <StatusLine tone="danger">
                  Yuqori yuklama: {hot.map((g) => g.label.toLowerCase()).join(', ')} — {RESOURCE_DANGER_AT}% dan oshdi
                </StatusLine>
              ) : (
                <StatusLine tone="success">Resurslar me'yorida</StatusLine>
              )}
            </div>
          );
        }}
      </ResourceBody>
    </IntelPanel>
  );
}
