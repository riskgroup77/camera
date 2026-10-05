import { useEffect, useState } from 'react';
import { ApiError, api, isAbortError } from '../../lib/apiClient';
import { formatNumber, formatPercent, IntelPanel, MicroLabel, ProgressBar, Skeleton, StatusLamp } from '../../ui';

interface ParentCoverage {
  students: number;
  telegramLinked: number;
  phoneOnly: number;
  enabled: number;
  arrivalEnabled: boolean;
  absenceEnabled: boolean;
  weekSent: number;
  weekFailed: number;
  weekSkipped: number;
}

/** Ota-onaga davomat xabari: nechta ota-ona bog'langan va so'nggi 7 kunda
 *  xabarlar yetib borganmi (GET /api/notifications/ota-ona). */
export function ParentCoverageCard() {
  const [data, setData] = useState<ParentCoverage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .get<ParentCoverage>('/api/notifications/ota-ona', undefined, { signal: controller.signal })
      .then(setData)
      .catch((err) => {
        if (!isAbortError(err)) setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, []);

  const reachable = data ? data.telegramLinked + data.phoneOnly : 0;
  const pct = data && data.students ? Math.round((reachable / data.students) * 1000) / 10 : null;
  const attempted = data ? data.weekSent + data.weekFailed : 0;

  return (
    <IntelPanel title="Ota-onaga xabar" bodyClassName="flex flex-col gap-3 p-3 text-[13px]">
      {error && <p className="text-danger">{error}</p>}
      {!data && !error && <Skeleton className="h-24" />}
      {data && (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <StatusLamp status={data.arrivalEnabled ? 'ok' : 'idle'} label={`Keldi xabari: ${data.arrivalEnabled ? 'yoqilgan' : "o'chiq"}`} />
            <StatusLamp status={data.absenceEnabled ? 'ok' : 'idle'} label={`Kelmadi xabari: ${data.absenceEnabled ? 'yoqilgan' : "o'chiq"}`} />
          </div>
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-muted">
                <span className="text-xl font-semibold tabular-nums text-fg">{formatNumber(reachable)}</span> / {formatNumber(data.students)} talabaning ota-onasi bog‘langan
              </span>
              <span className="font-semibold tabular-nums text-fg">{formatPercent(pct)}</span>
            </div>
            <ProgressBar value={pct} tone={pct !== null && pct >= 50 ? 'success' : 'warning'} className="mt-1.5" ariaLabel="Ota-ona qamrovi" />
            <p className="mt-1 text-[12px] text-muted">
              Telegram: {formatNumber(data.telegramLinked)} · faqat SMS: {formatNumber(data.phoneOnly)} · xabar yoqilgan: {formatNumber(data.enabled)}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-px border border-border bg-border">
            {(
              [
                ['7 kunda yetdi', data.weekSent, 'text-success'],
                ['Xato', data.weekFailed, data.weekFailed ? 'text-danger' : 'text-fg'],
                ["O'tkazildi", data.weekSkipped, 'text-muted'],
              ] as const
            ).map(([label, value, tone]) => (
              <div key={label} className="bg-surface px-2 py-1.5">
                <MicroLabel className="block">{label}</MicroLabel>
                <span className={`intel-code text-lg font-semibold ${tone}`}>{formatNumber(value)}</span>
              </div>
            ))}
          </div>
          {attempted > 0 && data.weekFailed / attempted > 0.2 && (
            <p className="text-[12px] text-warning">
              Xabarlarning beshdan biridan ko‘pi yetmagan — «Jurnal» tabida xato sababini ko‘ring va qayta yuboring.
            </p>
          )}
          <p className="text-[12px] text-muted">
            Ota-onani bog‘lash: talaba profilidagi «Ota-ona» maydonidan Telegram havolasini yuboring.
          </p>
        </>
      )}
    </IntelPanel>
  );
}
