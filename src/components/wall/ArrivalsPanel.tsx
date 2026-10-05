import { DoorOpen } from 'lucide-react';
import type { LastArrival } from '../../lib/situationApi';
import { CodeText, MicroLabel, attendanceMeta, cn, TONE_TEXT } from '../../ui';
import { WallFace, WallPanel } from './primitives';

/** Jonli kelishlar — yangisi tepada, yangi kelgani "suzib" kiradi. */
export function ArrivalsPanel({
  arrivals,
  freshIds,
  live = true,
}: {
  arrivals: LastArrival[];
  freshIds: ReadonlySet<string>;
  /** Server bilan aloqa bormi. Aloqa uzilganda "jonli" deyish yolg'on. */
  live?: boolean;
}) {
  return (
    <WallPanel
      area="B"
      title="Jonli kelish"
      icon={<DoorOpen />}
      aside={
        live ? (
          <span className="flex items-center gap-[0.4em]">
            <span className="relative flex h-[0.5em] w-[0.5em]">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-[1px] bg-success opacity-60" />
              <span className="relative inline-flex h-full w-full rounded-[1px] bg-success" />
            </span>
            <MicroLabel className="!text-success">jonli</MicroLabel>
          </span>
        ) : (
          <span className="flex items-center gap-[0.4em]">
            <span className="inline-flex h-[0.5em] w-[0.5em] rounded-[1px] bg-danger" />
            <MicroLabel className="!text-danger">aloqa yo'q</MicroLabel>
          </span>
        )
      }
    >
      {arrivals.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center text-center text-muted">
          <DoorOpen className="mb-[0.5em] h-[2.5em] w-[2.5em] opacity-50" />
          <div className="text-[1.1em] font-semibold text-fg">Hali hech kim kelmadi</div>
        </div>
      ) : (
        <ul className="flex min-h-0 flex-1 flex-col gap-[0.55em] overflow-hidden" aria-live="polite">
          {arrivals.map((a, i) => {
            const meta = attendanceMeta(a.status);
            return (
              <li
                /* Kalitda vaqt bo'lgani uchun server yozuvi jonli yozuvni
                   almashtirganda qator qaytadan yaratilib, animatsiya
                   ikkinchi marta o'ynardi. */
                key={a.id}
                className={cn(
                  'flex shrink-0 items-center gap-[0.8em] border border-border bg-surface-2 p-[0.45em] pe-[0.9em] transition-colors duration-1000',
                  freshIds.has(a.id) && 'wall-arrive border-success bg-success-soft',
                  i > 0 && 'opacity-[var(--fade)]',
                )}
                style={{ ['--fade' as string]: String(Math.max(0.55, 1 - i * 0.05)) }}
              >
                <WallFace photoUrl={a.photoUrl} initials={a.initials} status={a.status} className="h-[3.6em] w-[3.6em] shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[1.1em] font-semibold text-fg">{a.fullName}</div>
                  <div className="truncate text-[0.75em] text-muted">
                    {a.type === 'talaba' ? 'Talaba' : 'Xodim'}
                    {a.unit ? ` · ${a.unit}` : ''}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <CodeText className="block text-[1.5em] font-semibold leading-none text-fg">{a.time}</CodeText>
                  <div className={cn('intel-micro mt-[0.35em] !text-[0.6em]', TONE_TEXT[meta.tone])}>{meta.label}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </WallPanel>
  );
}
