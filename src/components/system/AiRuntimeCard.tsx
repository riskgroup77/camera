import { ChevronDown } from 'lucide-react';
import { CodeText, IntelPanel, MicroLabel, StatusLamp, cn, formatNumber, rag, type IntelStatus } from '../../ui';
import { formatDuration } from '../../lib/integrationsApi';
import type { LiveResource } from '../situation/useLiveResource';
import { MeasuredAt, Metric, Recommendation, ResourceBody, StatusLine, formatServerTime } from './parts';
import { sweepLabel, type SweepStatus, type SystemAiStatus } from './systemTypes';

/** Navbat chuqurligi — chegarasi bor: bo'sh navbat yashil, 4 tagacha
 *  sariq, undan ortiq qizil (teskari shkala: kam bo'lgani yaxshi). */
const QUEUE_RAG = { ok: 0, warn: 4 };
/** Slot bandligi (%) — 80% gacha yashil, to'lib ketsa qizil. */
const SLOT_RAG = { ok: 80, warn: 100 };

function sweepState(sweep: SweepStatus): { label: string; status: IntelStatus } {
  if (sweep.lastError) return { label: 'Xato', status: 'alert' };
  if (sweep.lagging) return { label: 'Kechikmoqda', status: 'warn' };
  if (sweep.paused) return { label: 'Pauzada', status: 'idle' };
  if (sweep.running) return { label: 'Ishlamoqda', status: 'ok' };
  return { label: 'Normal', status: 'ok' };
}

const seconds = (value: number) => `${formatNumber(value, 1)} s`;

/**
 * AI infratuzilma — o'lchov bloki.
 *
 * Navbat chuqurligi va slot bandligi uchun chegara bor — svetofor bilan.
 * "Oxirgi siklda N modul" — sanoq: modul soni sozlamaga bog'liq, ko'p
 * yoki kam bo'lgani o'z-o'zidan yaxshi yoki yomon emas, betaraf qoladi.
 */
export function AiRuntimeCard({ resource }: { resource: LiveResource<SystemAiStatus> }) {
  return (
    <IntelPanel title="AI infratuzilma" brackets={false} right={<MeasuredAt resource={resource} />}>
      <ResourceBody resource={resource} lines={6}>
        {(ai) => {
          const sweeps = ai.sweeps ?? [];
          const entrance = sweeps.find((s) => s.name === 'entrance_exit_attendance');
          const lagging = sweeps.filter((s) => s.lagging);
          const failing = sweeps.filter((s) => s.lastError);
          const paused = sweeps.filter((s) => s.paused);
          const gpuActive = ai.gpu.faceGpuActive || ai.gpu.objectGpuActive;
          // Chiroq yashil bo'lib, yozuvda "CPU ishlatilmoqda" turishi mumkin edi: rang
          // face||object bo'yicha, yozuv esa faqat face bo'yicha hisoblanardi.
          const gpuParts = [ai.gpu.faceGpuActive ? 'yuz' : null, ai.gpu.objectGpuActive ? 'obyekt' : null].filter(Boolean);
          const gpuLabel = !ai.gpu.cudaAvailable
            ? "yo'q, CPU'da"
            : gpuActive
              ? `CUDA faol (${gpuParts.join(', ')})`
              : 'mavjud, CPU ishlatilmoqda';
          const tickAt = formatServerTime(ai.lastTick.finishedAt);
          const pollSeconds = ai.schedulerPollSeconds ?? 0;
          const gate = ai.faceInferenceGate;
          const slotLoad = ai.sweepSlots.max > 0 ? (ai.sweepSlots.inUse / ai.sweepSlots.max) * 100 : null;
          return (
            <div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-border px-2.5 py-2">
                <StatusLamp status={gpuActive ? 'ok' : 'idle'} label={`GPU: ${gpuLabel}`} />
                <StatusLamp
                  status="ok"
                  label={`Rejalashtiruvchi: ${ai.schedulerEnabled ? 'parallel' : 'ketma-ket'}`}
                />
              </div>

              <div className="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-3">
                {/* Modul soni — sozlamaga bog'liq sanoq, hukmsiz. */}
                <Metric
                  label={pollSeconds > 0 ? `Oxirgi siklda (har ${formatDuration(pollSeconds)})` : 'Oxirgi siklda'}
                  value={formatNumber(ai.lastTick.modulesRan)}
                  unit="modul"
                  hint={tickAt ?? undefined}
                />
                <Metric
                  label="Parallel slotlar"
                  value={`${ai.sweepSlots.inUse} / ${ai.sweepSlots.max}`}
                  unit="band/jami"
                  // max = 0 bo'lsa 0 >= 0 rost bo'lib, bo'sh navbat sariq ko'rinardi:
                  // o'lchanmagan slot hukmsiz ("yoq") qoladi.
                  verdict={rag(slotLoad, SLOT_RAG)}
                  hint={slotLoad === null ? 'Sozlanmagan' : `${formatNumber(slotLoad, 0)}%`}
                />
                <Metric
                  label="Yuz tanish navbati"
                  value={`${gate.inUse} / ${gate.max}`}
                  unit="band/jami"
                  verdict={rag(gate.waiting, QUEUE_RAG)}
                  hint={gate.waiting > 0 ? `${gate.waiting} kutmoqda` : undefined}
                />
              </div>

              <div className="divide-y divide-border border-b border-border">
                {(ai.entranceWatchers ?? 0) > 0 ? (
                  <StatusLine tone="success">
                    Kirish/chiqish: <CodeText>{ai.entranceWatchers}</CodeText> ta kamera doimiy kuzatuvda
                  </StatusLine>
                ) : (
                  entrance && (
                    <StatusLine tone="success">
                      Kirish/chiqish: har <CodeText>{formatDuration(entrance.intervalSeconds)}</CodeText>, oxirgisi{' '}
                      <CodeText>{seconds(entrance.lastDurationSeconds)}</CodeText>
                    </StatusLine>
                  )
                )}
                {ai.lastTick.modulesRan > 0 && (
                  <StatusLine tone={ai.lastTick.skippedOverlap ? 'warning' : 'neutral'}>
                    Eng uzun modul <CodeText>{seconds(ai.lastTick.durationSeconds)}</CodeText> ishladi
                    {ai.lastTick.skippedOverlap ? " — bir sikl o'tkazildi" : ''}
                  </StatusLine>
                )}
                {paused.length > 0 && <StatusLine tone="info">Pauzada: {paused.map((s) => sweepLabel(s.name)).join(', ')}</StatusLine>}
                {lagging.length > 0 && <StatusLine tone="warning">Kechikayotgan: {lagging.map((s) => sweepLabel(s.name)).join(', ')}</StatusLine>}
                {failing.length > 0 && <StatusLine tone="danger">Xato bergan: {failing.map((s) => sweepLabel(s.name)).join(', ')}</StatusLine>}
              </div>

              {sweeps.length > 0 && (
                <details className="group border-b border-border">
                  <summary className="flex cursor-pointer list-none items-center gap-2 bg-surface-2/60 px-2.5 py-1.5 [&::-webkit-details-marker]:hidden">
                    <MicroLabel className="!text-fg">Fon vazifalari</MicroLabel>
                    <CodeText className="text-[11px] text-subtle">{sweeps.length}</CodeText>
                    <ChevronDown size={14} className="ms-auto text-subtle transition-transform group-open:rotate-180" aria-hidden="true" />
                  </summary>
                  <ul className="divide-y divide-border border-t border-border">
                    {sweeps.map((sweep) => {
                      const state = sweepState(sweep);
                      return (
                        <li key={sweep.name} className="flex items-center gap-3 px-2.5 py-1.5">
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[13px] text-fg">{sweepLabel(sweep.name)}</p>
                            <p className="intel-code truncate text-[11px] text-muted">
                              {sweep.tier === 'critical' ? 'Kritik' : 'Standart'} · har {formatDuration(sweep.intervalSeconds)} · oxirgisi {seconds(sweep.lastDurationSeconds)} ·{' '}
                              {formatNumber(sweep.runs)} marta
                              {sweep.failures > 0 ? ` · ${formatNumber(sweep.failures)} xato` : ''}
                              {formatServerTime(sweep.lastFinishedAt) ? ` · ${formatServerTime(sweep.lastFinishedAt)}` : ''}
                            </p>
                            {sweep.lastError && <p className="mt-0.5 break-words text-xs text-danger">Xato: {sweep.lastError}</p>}
                          </div>
                          <StatusLamp className={cn('shrink-0')} status={state.status} label={state.label} pulse={sweep.running} />
                        </li>
                      );
                    })}
                  </ul>
                </details>
              )}

              <Recommendation>{ai.gpu.recommendation}</Recommendation>
            </div>
          );
        }}
      </ResourceBody>
    </IntelPanel>
  );
}
