import { Pause, Play, Repeat } from 'lucide-react';
import { Button, Input, Tabs } from '../../ui';
import {
  TOUR_MAX_SECONDS,
  TOUR_MIN_SECONDS,
  normalizeTourInterval,
  type TourKind,
  type WallView,
} from '../../lib/videoWall';
import WallPopover from './WallPopover';

export interface TourSettings {
  kind: TourKind;
  intervalSec: number;
  /** Turda qatnashadigan ko'rinishlar; bo'sh — hammasi. */
  viewIds: string[];
}

export const DEFAULT_TOUR: TourSettings = { kind: 'views', intervalSec: 20, viewIds: [] };

/** localStorage'dan o'qilgan tur sozlamasini tekshirish. */
export function sanitizeTour(raw: unknown): TourSettings {
  const value = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  return {
    kind: value.kind === 'pages' ? 'pages' : 'views',
    intervalSec: normalizeTourInterval(value.intervalSec),
    viewIds: Array.isArray(value.viewIds) ? value.viewIds.filter((id): id is string => typeof id === 'string') : [],
  };
}

const KIND_TABS = [
  { id: 'views' as const, label: "Ko'rinishlar" },
  { id: 'pages' as const, label: 'Kamera sahifalari' },
];

/** Aylanish (tur): saqlangan ko'rinishlar yoki filtrlangan kameralar
 * sahifalari har N soniyada almashadi. Katak kattalashtirilganda yoki
 * varaq fonda bo'lsa tur to'xtab turadi. */
export default function TourMenu({
  settings,
  onChange,
  running,
  onToggle,
  views,
  pages,
  align = 'right',
}: {
  settings: TourSettings;
  onChange: (next: TourSettings) => void;
  running: boolean;
  onToggle: () => void;
  views: WallView[];
  pages: number;
  align?: 'left' | 'right';
}) {
  const selected = new Set(settings.viewIds);
  const canRun = settings.kind === 'views' ? views.length >= 2 : pages >= 2;

  return (
    <WallPopover
      icon={<Repeat size={16} aria-hidden="true" className={running ? 'animate-spin [animation-duration:3s] motion-reduce:animate-none' : undefined} />}
      label={running ? `Tur · ${settings.intervalSec}s` : 'Tur'}
      active={running}
      title="Aylanish rejimi (T)"
      align={align}
      widthClass="w-72"
    >
      {() => (
        <div className="space-y-3 text-[13px]">
          <p className="text-sm font-semibold">Aylanish rejimi</p>
          <Tabs
            variant="segmented"
            size="sm"
            ariaLabel="Tur turi"
            tabs={KIND_TABS}
            value={settings.kind}
            onChange={(kind) => onChange({ ...settings, kind })}
            className="w-full [&>button]:flex-1 [&>button]:justify-center"
          />

          <div>
            <label className="block font-medium text-fg" htmlFor="videowall-tour-range">
              Almashish oralig&apos;i: <span className="tabular-nums">{settings.intervalSec}</span> soniya
            </label>
            <div className="mt-1.5 flex items-center gap-2">
              <input
                id="videowall-tour-range"
                type="range"
                min={TOUR_MIN_SECONDS}
                max={120}
                step={5}
                value={Math.min(settings.intervalSec, 120)}
                onChange={(event) => onChange({ ...settings, intervalSec: normalizeTourInterval(Number(event.target.value)) })}
                className="min-w-0 flex-1 accent-primary"
              />
              <Input
                type="number"
                size="sm"
                min={TOUR_MIN_SECONDS}
                max={TOUR_MAX_SECONDS}
                value={settings.intervalSec}
                onChange={(event) => onChange({ ...settings, intervalSec: normalizeTourInterval(Number(event.target.value)) })}
                aria-label="Oraliq (soniya)"
                className="w-20 shrink-0"
              />
            </div>
          </div>

          {settings.kind === 'views' ? (
            <div>
              <p className="mb-1 font-medium text-fg">Qaysi ko&apos;rinishlar</p>
              <p className="mb-1.5 text-xs text-muted">Tanlanmasa — hammasi.</p>
              {views.length === 0 ? (
                <p className="text-muted">Avval ko&apos;rinishlarni saqlang.</p>
              ) : (
                <ul className="max-h-40 space-y-0.5 overflow-y-auto">
                  {views.map((view) => (
                    <li key={view.id}>
                      <label className="flex items-center gap-2 rounded-[6px] px-1.5 py-1 hover:bg-surface-2">
                        <input
                          type="checkbox"
                          checked={selected.has(view.id)}
                          onChange={(event) => {
                            const next = new Set(selected);
                            if (event.target.checked) next.add(view.id);
                            else next.delete(view.id);
                            onChange({ ...settings, viewIds: [...next] });
                          }}
                          className="h-4 w-4 accent-primary"
                        />
                        <span className="truncate">{view.name}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-muted">
              Yon paneldagi filtrga mos kameralar setka sig&apos;imi bo&apos;yicha sahifalanadi ({pages} sahifa).
            </p>
          )}

          <Button
            variant={running ? 'danger' : 'primary'}
            icon={running ? Pause : Play}
            fullWidth
            onClick={onToggle}
            disabled={!running && !canRun}
          >
            {running ? "To'xtatish" : 'Boshlash'}
          </Button>
          {!running && !canRun && (
            <p className="text-xs text-warning">
              {settings.kind === 'views' ? "Kamida 2 ta ko'rinish kerak." : "Kamida 2 sahifa bo'lishi kerak."}
            </p>
          )}
        </div>
      )}
    </WallPopover>
  );
}
