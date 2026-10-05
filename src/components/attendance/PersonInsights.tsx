import { QrCode, ScanFace } from 'lucide-react';
import { ButtonLink, Button, MicroLabel, CodeText, IntelPanel, cn, formatPercent } from '../../ui';
import { LATE_CUTOFF_MINUTES, type PersonKpis, type WeekdayStat } from '../../lib/studentAttendance';
import { KpiReadout, type KpiItem } from './readout';

function minutesClock(m: number | null | undefined): string {
  if (m === null || m === undefined) return '—';
  const h = Math.floor(m / 60);
  return `${String(h).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`;
}

/** Oldingi davrga nisbatan o'zgarish — qisqa izoh.
 *  Oldingi davrda yozuv bo'lmasa taqqoslash umuman yozilmaydi: "+14"
 *  yo'qdan paydo bo'lgandek ko'rinardi. */
function deltaText(cur: number | null, prev: number | null | undefined, unit: string): string | undefined {
  if (cur === null || prev === null || prev === undefined) return undefined;
  const v = Math.round((cur - prev) * 10) / 10;
  return `Oldingi davrga ${v > 0 ? '+' : ''}${v.toLocaleString('ru-RU')}${unit}`;
}

/** Xodim uchun davr KPI'lari: oldingi xuddi shunday davrga nisbatan o'zgarish bilan. */
export function StaffKpis({
  current,
  previous,
  lateCutoff = LATE_CUTOFF_MINUTES,
}: {
  current: PersonKpis;
  previous: PersonKpis | null;
  /** Kechikish chegarasi (daqiqa) — attendance_policy. */
  lateCutoff?: number;
}) {
  const items: KpiItem[] = [
    {
      label: 'Davomat',
      value: formatPercent(current.rate, 1),
      rate: current.rate,
      // Maxraj — yozuvi bor kunlar, davrdagi hamma kun emas.
      hint: `${current.presentDays} / ${current.presentDays + current.absentDays} yozuv bor kun`,
    },
    {
      label: "O'rtacha kelish",
      value: minutesClock(current.avgArrivalMinutes),
      // Vaqt — foiz emas: unga davomat svetofori qo'yilmaydi.
      hint: `chegara ${minutesClock(lateCutoff)}`,
    },
    { label: 'Kech kelgan', value: `${current.lateDays} kun` },
    { label: 'Kelmagan', value: `${current.absentDays} kun`, hint: deltaText(current.absentDays, previous?.absentDays, '') },
  ];
  return <KpiReadout className="lg:grid-cols-4" items={items} />;
}

/** Hafta kunlari naqshi: o'rtacha kelish va kechikishlar — qaysi kun "og'ir". */
export function WeekdayPatternCard({ rows, lateCutoff = LATE_CUTOFF_MINUTES }: { rows: WeekdayStat[]; lateCutoff?: number }) {
  const withData = rows.filter((r) => r.days > 0);
  const worst = withData.reduce<WeekdayStat | null>((w, r) => (!w || r.late + r.absent > w.late + w.absent ? r : w), null);
  // Shkala: 07:30 … 10:00
  const lo = 450;
  const hi = 600;
  const pos = (m: number) => `${Math.min(100, Math.max(0, ((m - lo) / (hi - lo)) * 100))}%`;
  return (
    <IntelPanel title="Hafta kunlari" code={minutesClock(lateCutoff)}>
      {worst && worst.late + worst.absent > 0 && (
        <p className="border-b border-border px-3 py-1.5 text-[12px] text-muted">
          Eng og&apos;ir: <span className="font-medium text-fg">{worst.label}</span> — {worst.late} kech, {worst.absent} kelmagan
        </p>
      )}
      {withData.length === 0 ? (
        <p className="px-3 py-6 text-center text-[13px] text-muted">Yozuv yo&apos;q</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.weekday} className="grid grid-cols-[2.5rem_minmax(0,1fr)_3.5rem_5.5rem] items-center gap-3 px-3 py-1.5 text-[13px]">
              <span className={cn('font-medium', r === worst && r.late + r.absent > 0 ? 'text-warning' : 'text-fg')}>{r.label}</span>
              <div className="relative h-2 bg-surface-2" aria-hidden="true">
                <span className="absolute inset-y-[-3px] w-px bg-warning" style={{ left: pos(lateCutoff) }} />
                {r.avgArrivalMinutes !== null && (
                  <span
                    className={cn(
                      'absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 border border-surface',
                      r.avgArrivalMinutes > lateCutoff ? 'bg-warning' : 'bg-primary',
                    )}
                    style={{ left: pos(r.avgArrivalMinutes) }}
                  />
                )}
              </div>
              <CodeText className="text-right font-semibold text-fg">{minutesClock(r.avgArrivalMinutes)}</CodeText>
              <span className="intel-code text-right text-[11px] text-muted">
                {r.days === 0 ? '—' : (
                  <>
                    <span className={r.late ? 'font-semibold text-warning' : undefined}>{r.late}</span> kech
                    {r.absent > 0 && <span className="text-danger"> · {r.absent}</span>}
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </IntelPanel>
  );
}

/** Yuzi yo'q odam uchun: nima uchun davomat yo'qligi va qanday tuzatish. */
export function EnrollCta({ student, group, pending, onOpenGroup, registryLink }: { student: boolean; group: string | null; pending: boolean; onOpenGroup?: () => void; registryLink: string }) {
  const enrollLink = `/royxatdan-otish${group ? `?guruh=${encodeURIComponent(group)}` : ''}`;
  return (
    <div className="flex flex-col gap-3 border border-primary/40 bg-primary-soft px-3 py-2.5 sm:flex-row sm:items-center">
      <ScanFace size={20} aria-hidden="true" className="shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <MicroLabel>{pending ? 'Yuzi tasdiq kutmoqda' : "Yuzi topshirilmagan"}</MicroLabel>
        <p className="mt-0.5 text-[13px] leading-relaxed text-fg">
          Kameralar taniy olmaydi — bo&apos;sh kunlar «kelmagan» degani emas.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {pending ? (
          <ButtonLink to={registryLink} size="sm" variant="primary">
            Reestrda tasdiqlash
          </ButtonLink>
        ) : student ? (
          <>
            {onOpenGroup && group && (
              <Button size="sm" variant="primary" icon={QrCode} onClick={onOpenGroup}>
                Guruh QR kartasi
              </Button>
            )}
            <ButtonLink to={enrollLink} size="sm" variant="secondary">
              Ro&apos;yxatdan o&apos;tish
            </ButtonLink>
          </>
        ) : (
          <ButtonLink to={registryLink} size="sm" variant="primary">
            Reestrda qo&apos;shish
          </ButtonLink>
        )}
      </div>
    </div>
  );
}
