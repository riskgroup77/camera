import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import {
  ArrowDown,
  ArrowDownLeft,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  Bookmark,
  ChevronDown,
  ChevronUp,
  Gamepad2,
  Loader2,
  MapPin,
  RefreshCw,
  Square,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import { usePersistedState } from '../../lib/usePersistedState';
import {
  PTZ_HOLD_DURATION_MS,
  PTZ_KEEPALIVE_MS,
  createPtzCommandQueue,
  ptzApi,
  type PtzPreset,
  type PtzVelocity,
} from '../../lib/ptzApi';

/** PTZ boshqaruv paneli: yo'nalish tugmalari (bosib turish — harakat,
 * qo'yib yuborish — to'xtash), zoom, tezlik, presetlar.
 *
 * Xavfsizlik to'ri: har bir harakat buyrug'i serverga `durationMs` bilan
 * ketadi va tugma bosib turilgan paytda davriy yangilanadi. Brauzer
 * "to'xtash"ni yubora olmay qolsa (tarmoq uzildi, varaq yopildi, sichqoncha
 * oynadan chiqib ketdi), kamera baribir 2 soniyada o'zi to'xtaydi.
 *
 * Klaviatura: panel fokusda bo'lganda (yoki `globalKeyboard` bilan
 * butun oynada) strelkalar — burish/egish (ikkitasi birga — diagonal),
 * `+`/`-` — yaqinlashtirish/uzoqlashtirish. */

type Axis = 'left' | 'right' | 'up' | 'down' | 'in' | 'out';

const KEY_AXES: Record<string, Axis> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'up',
  ArrowDown: 'down',
  '+': 'in',
  '=': 'in',
  PageUp: 'in',
  '-': 'out',
  _: 'out',
  PageDown: 'out',
};

const PAD: Array<{ axes: Axis[]; icon: typeof ArrowUp; label: string } | null> = [
  { axes: ['up', 'left'], icon: ArrowUpLeft, label: 'Yuqori-chapga' },
  { axes: ['up'], icon: ArrowUp, label: 'Yuqoriga' },
  { axes: ['up', 'right'], icon: ArrowUpRight, label: "Yuqori-o'ngga" },
  { axes: ['left'], icon: ArrowLeft, label: 'Chapga' },
  null,
  { axes: ['right'], icon: ArrowRight, label: "O'ngga" },
  { axes: ['down', 'left'], icon: ArrowDownLeft, label: 'Quyi-chapga' },
  { axes: ['down'], icon: ArrowDown, label: 'Pastga' },
  { axes: ['down', 'right'], icon: ArrowDownRight, label: "Quyi-o'ngga" },
];

function velocityFor(axes: ReadonlySet<Axis>, speed: number): PtzVelocity {
  const dir = (plus: Axis, minus: Axis) => (axes.has(plus) ? 1 : 0) - (axes.has(minus) ? 1 : 0);
  return {
    pan: dir('right', 'left') * speed,
    tilt: dir('up', 'down') * speed,
    zoom: dir('in', 'out') * speed,
  };
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : "Tarmoq xatosi — PTZ buyrug'i yuborilmadi";
}

export default function PtzControls({
  cameraId,
  className = '',
  globalKeyboard = false,
  defaultOpen = true,
}: {
  cameraId: string;
  className?: string;
  /** true — strelkalar butun oynada ishlaydi (videodevorning kattalashtirilgan katagi). */
  globalKeyboard?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [speed, setSpeed] = usePersistedState<number>('ptz-speed', 0.5);
  const safeSpeed = Number.isFinite(speed) ? Math.min(1, Math.max(0.1, speed)) : 0.5;
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<ReadonlySet<Axis>>(new Set());
  const [presets, setPresets] = useState<PtzPreset[] | null>(null);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [newPreset, setNewPreset] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyPreset, setBusyPreset] = useState<string | null>(null);

  const pointerAxes = useRef<Set<Axis>>(new Set());
  const keyAxes = useRef<Set<Axis>>(new Set());
  const moving = useRef(false);
  const keepAlive = useRef<number | undefined>(undefined);
  const speedRef = useRef(safeSpeed);
  speedRef.current = safeSpeed;

  const queue = useMemo(
    () =>
      createPtzCommandQueue(
        (command) =>
          command.kind === 'stop'
            ? ptzApi.stop(cameraId)
            : ptzApi.move(cameraId, command.velocity, PTZ_HOLD_DURATION_MS),
        (err) => setError(errorText(err)),
      ),
    [cameraId],
  );

  useEffect(() => {
    if (!error) return;
    const timer = window.setTimeout(() => setError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [error]);

  /** Bosilgan tugmalar/strelkalar birlashmasidan tezlikni hisoblab yuboradi. */
  const apply = useCallback(() => {
    const axes = new Set<Axis>([...pointerAxes.current, ...keyAxes.current]);
    setActive(axes);
    const velocity = velocityFor(axes, speedRef.current);
    const still = velocity.pan === 0 && velocity.tilt === 0 && velocity.zoom === 0;
    if (keepAlive.current !== undefined) {
      window.clearInterval(keepAlive.current);
      keepAlive.current = undefined;
    }
    if (still) {
      if (moving.current) {
        moving.current = false;
        queue.push({ kind: 'stop' });
      }
      return;
    }
    moving.current = true;
    queue.push({ kind: 'move', velocity });
    keepAlive.current = window.setInterval(() => {
      queue.push({ kind: 'move', velocity: velocityFor(new Set([...pointerAxes.current, ...keyAxes.current]), speedRef.current) });
    }, PTZ_KEEPALIVE_MS);
  }, [queue]);

  const releaseAll = useCallback(() => {
    if (pointerAxes.current.size === 0 && keyAxes.current.size === 0) return;
    pointerAxes.current.clear();
    keyAxes.current.clear();
    apply();
  }, [apply]);

  // Kamera almashsa yoki panel yopilsa — harakat to'xtatiladi.
  useEffect(
    () => () => {
      if (keepAlive.current !== undefined) window.clearInterval(keepAlive.current);
      keepAlive.current = undefined;
      if (moving.current) {
        moving.current = false;
        void ptzApi.stop(cameraId).catch(() => {});
      }
      pointerAxes.current.clear();
      keyAxes.current.clear();
    },
    [cameraId],
  );

  // Oyna fokusni yo'qotsa (Alt+Tab tugma bosib turilganda) — to'xtatish:
  // aks holda keyup hech qachon kelmaydi.
  useEffect(() => {
    window.addEventListener('blur', releaseAll);
    return () => window.removeEventListener('blur', releaseAll);
  }, [releaseAll]);

  const loadPresets = useCallback(async () => {
    setPresetsLoading(true);
    setPresetsError(null);
    try {
      setPresets(await ptzApi.presets(cameraId));
    } catch (err) {
      setPresets(null);
      setPresetsError(errorText(err));
    } finally {
      setPresetsLoading(false);
    }
  }, [cameraId]);

  useEffect(() => {
    setPresets(null);
    setPresetsError(null);
    if (open) void loadPresets();
  }, [open, loadPresets]);

  function handleKey(event: KeyboardEvent | ReactKeyboardEvent, down: boolean): boolean {
    if (event.ctrlKey || event.metaKey || event.altKey) return false;
    const axis = KEY_AXES[event.key];
    if (!axis) return false;
    event.preventDefault();
    if (down && event.repeat) return true;
    const had = keyAxes.current.has(axis);
    if (down && !had) keyAxes.current.add(axis);
    else if (!down && had) keyAxes.current.delete(axis);
    else return true;
    apply();
    return true;
  }

  useEffect(() => {
    if (!globalKeyboard) return;
    const onDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (handleKey(event, true)) event.stopPropagation();
    };
    const onUp = (event: KeyboardEvent) => {
      if (KEY_AXES[event.key]) handleKey(event, false);
    };
    // capture: videodevorning o'z strelka tugmalari (sahifalash) ishlamasin.
    window.addEventListener('keydown', onDown, true);
    window.addEventListener('keyup', onUp, true);
    return () => {
      window.removeEventListener('keydown', onDown, true);
      window.removeEventListener('keyup', onUp, true);
    };
    // handleKey faqat ref'lar va apply'ga tayanadi — har renderda qayta
    // yaratilsa ham xatti-harakati bir xil.
  }, [globalKeyboard, apply]);

  function pointerStart(axes: Axis[]) {
    return (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      pointerAxes.current = new Set(axes);
      apply();
    };
  }

  function pointerEnd() {
    if (pointerAxes.current.size === 0) return;
    pointerAxes.current.clear();
    apply();
  }

  async function gotoPreset(token: string) {
    setBusyPreset(token);
    try {
      await ptzApi.gotoPreset(cameraId, token);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusyPreset(null);
    }
  }

  async function savePreset() {
    const name = newPreset.trim();
    if (!name) return;
    setSaving(true);
    try {
      await ptzApi.savePreset(cameraId, name);
      setNewPreset('');
      await loadPresets();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  const holdButton = (axes: Axis[], label: string, children: ReactNode, extra = '') => {
    const pressed = axes.every((axis) => active.has(axis)) && axes.length > 0;
    return (
      <button
        type="button"
        aria-label={label}
        title={label}
        onPointerDown={pointerStart(axes)}
        onPointerUp={pointerEnd}
        onPointerCancel={pointerEnd}
        onLostPointerCapture={pointerEnd}
        onContextMenu={(event) => event.preventDefault()}
        className={`flex touch-none select-none items-center justify-center rounded-lg transition-colors ${
          pressed ? 'bg-primary text-primary-fg' : 'bg-white/10 text-white/85 hover:bg-white/20'
        } ${extra}`}
      >
        {children}
      </button>
    );
  };

  return (
    <div
      className={`w-60 rounded-card bg-black/80 p-2.5 text-white shadow-xl ring-1 ring-white/10 backdrop-blur ${className}`}
      tabIndex={0}
      onKeyDown={(event) => {
        if (!globalKeyboard && !isTypingTarget(event.target)) handleKey(event, true);
      }}
      onKeyUp={(event) => {
        if (!globalKeyboard && !isTypingTarget(event.target)) handleKey(event, false);
      }}
      onDoubleClick={(event) => event.stopPropagation()}
      aria-label="PTZ boshqaruvi"
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 text-xs font-bold"
      >
        <span className="flex items-center gap-1.5">
          <Gamepad2 size={14} aria-hidden="true" className="text-primary" />
          PTZ boshqaruvi
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>

      {open && (
        <div className="mt-2.5 space-y-2.5">
          <div className="flex items-stretch gap-2">
            <div className="grid flex-1 grid-cols-3 gap-1">
              {PAD.map((cell, index) =>
                cell ? (
                  <div key={index} className="aspect-square">
                    {holdButton(cell.axes, cell.label, <cell.icon size={16} />, 'h-full w-full')}
                  </div>
                ) : (
                  <button
                    key={index}
                    type="button"
                    aria-label="To'xtatish"
                    title="To'xtatish"
                    onClick={() => {
                      releaseAll();
                      queue.push({ kind: 'stop' });
                    }}
                    className="flex aspect-square items-center justify-center rounded-lg bg-danger/80 text-danger-fg hover:bg-danger"
                  >
                    <Square size={12} className="fill-white" />
                  </button>
                ),
              )}
            </div>
            <div className="flex w-10 flex-col gap-1">
              {holdButton(['in'], 'Yaqinlashtirish', <ZoomIn size={16} />, 'flex-1')}
              {holdButton(['out'], 'Uzoqlashtirish', <ZoomOut size={16} />, 'flex-1')}
            </div>
          </div>

          <label className="block text-[10px] font-semibold text-white/60">
            Tezlik: {Math.round(safeSpeed * 100)}%
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={Math.round(safeSpeed * 100)}
              onChange={(event) => setSpeed(Number(event.target.value) / 100)}
              className="mt-1 w-full accent-primary"
            />
          </label>

          <div>
            <div className="mb-1 flex items-center justify-between text-[10px] font-semibold text-white/60">
              <span className="flex items-center gap-1">
                <MapPin size={11} />
                Presetlar
              </span>
              <button
                type="button"
                onClick={() => void loadPresets()}
                aria-label="Presetlarni yangilash"
                className="rounded p-0.5 hover:bg-white/10"
              >
                <RefreshCw size={11} className={presetsLoading ? 'animate-spin' : ''} />
              </button>
            </div>
            {presetsError && <p className="text-[10px] text-warning">{presetsError}</p>}
            {presets && presets.length === 0 && <p className="text-[10px] text-white/40">Saqlangan preset yo&apos;q</p>}
            {presets && presets.length > 0 && (
              <ul className="max-h-28 space-y-0.5 overflow-y-auto pr-0.5">
                {presets.map((preset) => (
                  <li key={preset.token}>
                    <button
                      type="button"
                      onClick={() => void gotoPreset(preset.token)}
                      disabled={busyPreset !== null}
                      className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left text-[11px] hover:bg-white/10 disabled:opacity-60"
                    >
                      <span className="truncate">{preset.name}</span>
                      {busyPreset === preset.token ? (
                        <Loader2 size={11} className="shrink-0 animate-spin" />
                      ) : (
                        <span className="shrink-0 text-[10px] text-white/35">#{preset.token}</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <form
              className="mt-1.5 flex gap-1"
              onSubmit={(event) => {
                event.preventDefault();
                void savePreset();
              }}
            >
              <input
                value={newPreset}
                onChange={(event) => setNewPreset(event.target.value)}
                maxLength={64}
                placeholder="Joriy holat nomi"
                aria-label="Yangi preset nomi"
                className="min-w-0 flex-1 rounded-md bg-white/10 px-2 py-1 text-[11px] text-white outline-none placeholder:text-white/35 focus:bg-white/15"
              />
              <button
                type="submit"
                disabled={saving || !newPreset.trim()}
                title="Kameraning hozirgi holatini preset sifatida saqlash"
                className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-semibold text-primary-fg hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <Bookmark size={11} />}
                Saqlash
              </button>
            </form>
          </div>

          {error && <p className="rounded-md bg-danger/20 px-2 py-1 text-[10px] font-medium text-white">{error}</p>}
          <p className="text-[9px] leading-tight text-white/35">
            Bosib turing — harakat, qo&apos;yib yuboring — to&apos;xtaydi. Klaviatura: strelkalar, +/−.
          </p>
        </div>
      )}
    </div>
  );
}
