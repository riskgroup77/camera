import { useEffect, useRef, useState, type CSSProperties, type DragEvent } from 'react';
import { Loader2, Maximize2, Minimize2, Plus, X } from 'lucide-react';
import { CodeText, MicroLabel, StatusLamp, cn, type IntelStatus } from '../../ui';
import LiveVideoPlayer from '../LiveVideoPlayer';
import CameraThumbnail from './CameraThumbnail';
import PtzControls from '../ptz/PtzControls';
import { usePtzAvailability } from '../ptz/usePtzAvailability';
import { UNKNOWN_CAMERA_CODE, cameraPlaceCode } from './cameraCode';
import { formatWallTime, useWallClock } from './wallClock';
import type { TilePlayback } from '../../lib/videoWall';
import type { CameraFeed } from '../../types';

/** Sudrab tashlash ma'lumoti turlari — yon paneldan kamera yoki boshqa katak. */
export const DRAG_CAMERA = 'application/x-videodevor-camera';
export const DRAG_TILE = 'application/x-videodevor-tile';

/** Katak ekranda ko'rinyaptimi — ko'rinmayotgan katak pleyer ochmaydi
 * (masalan kichik oynada devor sahifa ichida qisman scroll bo'lganda). */
function useInView<T extends Element>() {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => setInView(entries.some((entry) => entry.isIntersecting)), {
      rootMargin: '50px',
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, inView] as const;
}

/** Burchak qisqichlari — katakni "nishon" kabi belgilaydi. Video ustida
 * oq, bo'sh/oflayn katakda esa qog'oz ranglari ishlatiladi. */
function TileBrackets({ tone }: { tone: 'video' | 'paper' }) {
  const color = tone === 'video' ? 'border-white/55' : 'border-border-strong';
  const base = 'pointer-events-none absolute h-2.5 w-2.5';
  return (
    <span aria-hidden="true">
      <span className={cn(base, 'left-0 top-0 border-l-2 border-t-2', color)} />
      <span className={cn(base, 'right-0 top-0 border-r-2 border-t-2', color)} />
      <span className={cn(base, 'bottom-0 left-0 border-b-2 border-l-2', color)} />
      <span className={cn(base, 'bottom-0 right-0 border-b-2 border-r-2', color)} />
    </span>
  );
}

/** Katakdagi jonli vaqt tamg'asi — butun devor uchun bitta taymerdan. */
function TileTime() {
  const now = useWallClock();
  return <CodeText className="shrink-0 text-[10px] text-white/75">{formatWallTime(now)}</CodeText>;
}

export default function WallTile({
  index,
  cameraId,
  camera,
  code = UNKNOWN_CAMERA_CODE,
  playback,
  style,
  startDelayMs,
  selected,
  maximized,
  editable,
  compact,
  pending = false,
  alarm = null,
  onSelect,
  onToggleMaximize,
  onRemove,
  onDropCamera,
  onDropTile,
  onStreamUnavailable,
}: {
  index: number;
  cameraId: string | null;
  /** null — katak bo'sh YOKI kamera ro'yxatda topilmadi (o'chirilgan). */
  camera: CameraFeed | null;
  /** Kameraning xizmat kodi (`CAM-084`) — `buildCameraCodes` dan. */
  code?: string;
  playback: TilePlayback;
  style: CSSProperties;
  startDelayMs: number;
  selected: boolean;
  maximized: boolean;
  editable: boolean;
  compact: boolean;
  /** Kameralar ro'yxati hali yuklanmoqda — "topilmadi" deyish erta. */
  pending?: boolean;
  /** Shu kamerada yaqinda yuqori muhimlikdagi hodisa (kriteriya nomi). */
  alarm?: string | null;
  onSelect: (index: number) => void;
  onToggleMaximize: (index: number) => void;
  onRemove: (index: number) => void;
  onDropCamera: (index: number, cameraId: string) => void;
  onDropTile: (from: number, to: number) => void;
  /** Oqim manzili yaroqsiz (403/404) — kameralar ro'yxatini yangilab,
   * yangi imzolangan havola olish kerak. */
  onStreamUnavailable?: () => void;
}) {
  const [ref, inView] = useInView<HTMLDivElement>();
  const [dragOver, setDragOver] = useState(false);
  const ptzAvailable = usePtzAvailability(maximized && camera && playback === 'live' ? camera.id : null, camera?.ptzEnabled);

  function handleDragOver(event: DragEvent) {
    if (!editable) return;
    const types = event.dataTransfer.types;
    if (types.includes(DRAG_CAMERA) || types.includes(DRAG_TILE)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = types.includes(DRAG_TILE) ? 'move' : 'copy';
      setDragOver(true);
    }
  }

  function handleDrop(event: DragEvent) {
    setDragOver(false);
    if (!editable) return;
    event.preventDefault();
    const droppedCamera = event.dataTransfer.getData(DRAG_CAMERA);
    if (droppedCamera) {
      onDropCamera(index, droppedCamera);
      return;
    }
    const from = Number(event.dataTransfer.getData(DRAG_TILE));
    if (Number.isInteger(from) && event.dataTransfer.getData(DRAG_TILE) !== '') onDropTile(from, index);
  }

  const isLive = camera?.status === 'live';
  const noVideo = isLive && camera?.hasVideo === false;
  const showLive = playback === 'live' && inView && Boolean(camera?.streamUrl);
  /** Oqim ROSTDAN o'ynayapti — "JONLI" yorlig'i faqat shu holatda. */
  const streaming = showLive && isLive && !noVideo;
  const place = cameraPlaceCode(camera);

  // Holat chirog'i: bitta matn — takrorlanmasin (ekranda sanaladi).
  const lamp: { status: IntelStatus; label: string; pulse: boolean } = streaming
    ? { status: 'alert', label: 'JONLI', pulse: true }
    : playback === 'snapshot'
      ? { status: 'warn', label: 'KADR', pulse: false }
      : playback === 'offline'
        ? { status: 'idle', label: noVideo ? 'TASVIRSIZ' : 'OFLAYN', pulse: false }
        : { status: 'warn', label: 'ULANMOQDA', pulse: false };

  /** Video ustidagi matn oq bo'lishi kerak — `intel-micro` ning odatdagi
   * kulrangi qorong'i kadrda o'qilmaydi. */
  const overVideo = '[&>.intel-micro]:!text-white/85';

  return (
    <div
      ref={ref}
      style={style}
      role="gridcell"
      aria-label={camera ? camera.name : cameraId ? "Noma'lum kamera" : "Bo'sh katak"}
      tabIndex={-1}
      draggable={editable && Boolean(cameraId) && !maximized}
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_TILE, String(index));
        event.dataTransfer.effectAllowed = 'move';
      }}
      onDragOver={handleDragOver}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => onSelect(index)}
      onDoubleClick={() => cameraId && onToggleMaximize(index)}
      className={cn(
        'group relative min-h-0 min-w-0 overflow-hidden rounded-[2px] bg-surface-2 outline-none',
        selected && !maximized && 'ring-2 ring-inset ring-primary',
        dragOver && 'ring-2 ring-inset ring-success',
        alarm && 'animate-pulse ring-4 ring-inset ring-danger',
      )}
    >
      {alarm && (
        <span className="absolute bottom-1 left-1 z-20 max-w-[90%] truncate rounded-[2px] bg-danger px-1.5 py-0.5 text-[11px] font-semibold text-white" title={alarm}>
          {alarm}
        </span>
      )}
      {!cameraId && (
        <div className="intel-grid flex h-full w-full flex-col items-center justify-center gap-1 border border-dashed border-border text-subtle">
          <Plus size={compact ? 14 : 18} aria-hidden="true" />
          {!compact && <MicroLabel className="px-2 text-center">Kamerani shu yerga torting</MicroLabel>}
        </div>
      )}

      {cameraId && !camera && (
        <div className="intel-grid flex h-full w-full flex-col items-center justify-center gap-1.5 text-muted">
          {pending && <Loader2 size={16} aria-hidden="true" className="animate-spin" />}
          <MicroLabel>{pending ? 'Yuklanmoqda' : "Ro'yxatda yo'q"}</MicroLabel>
          <CodeText className="text-[11px] text-subtle">{code}</CodeText>
        </div>
      )}

      {camera && showLive && (
        <LiveVideoPlayer
          streamUrl={camera.streamUrl}
          priority
          startDelayMs={startDelayMs}
          fit={maximized ? 'contain' : 'cover'}
          onStreamUnavailable={onStreamUnavailable}
        />
      )}

      {camera && (playback === 'snapshot' || (playback === 'live' && !showLive)) && (
        <CameraThumbnail cameraId={camera.id} alt={camera.name} className="h-full w-full" refreshMs={10_000} />
      )}

      {camera && playback === 'offline' && (
        <div className="intel-grid flex h-full w-full flex-col items-center justify-center gap-1.5 text-muted">
          <MicroLabel>{noVideo ? "Tasvir yo'q" : "Signal yo'q"}</MicroLabel>
          <CodeText className="text-[11px] text-subtle">{code}</CodeText>
        </div>
      )}

      {camera && (
        <>
          <div
            className={cn(
              'pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center gap-2 px-2 py-1',
              playback === 'offline' ? 'border-b border-border' : 'bg-gradient-to-b from-black/70 to-transparent',
            )}
          >
            <CodeText
              className={cn(
                'shrink-0 font-semibold',
                compact ? 'text-[9px]' : 'text-[10px]',
                playback === 'offline' ? 'text-muted' : 'text-white/90',
              )}
            >
              {code}
            </CodeText>
            {place && (
              <CodeText
                className={cn(
                  'shrink-0 text-[9px]',
                  playback === 'offline' ? 'text-subtle' : 'text-white/60',
                )}
              >
                {place}
              </CodeText>
            )}
            {!compact && (
              <span
                className={cn(
                  'truncate text-[11px] font-semibold tracking-tight',
                  playback === 'offline' ? 'text-fg' : 'text-white',
                )}
              >
                {camera.name}
              </span>
            )}
            <StatusLamp
              status={lamp.status}
              label={lamp.label}
              pulse={lamp.pulse}
              className={cn('ms-auto shrink-0', playback !== 'offline' && overVideo)}
            />
          </div>

          {!compact && (
            <div
              className={cn(
                'pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-center gap-2 px-2 py-1',
                playback === 'offline' ? 'border-t border-border' : 'bg-gradient-to-t from-black/70 to-transparent',
              )}
            >
              <MicroLabel className={cn('truncate', playback !== 'offline' && '!text-white/75')}>
                {[camera.building, camera.floor != null ? `${camera.floor}-qavat` : null, camera.zone]
                  .filter(Boolean)
                  .join(' · ') || 'Joy belgilanmagan'}
              </MicroLabel>
              <span className="ms-auto">
                {playback === 'offline' ? (
                  <CodeText className="shrink-0 text-[10px] text-subtle">{code}</CodeText>
                ) : (
                  <TileTime />
                )}
              </span>
            </div>
          )}
        </>
      )}

      <TileBrackets tone={camera && playback !== 'offline' ? 'video' : 'paper'} />

      {cameraId && (
        <div className="absolute right-1 top-6 z-20 flex gap-1 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onToggleMaximize(index);
            }}
            aria-label={maximized ? 'Kichraytirish' : 'Kattalashtirish'}
            title={maximized ? 'Kichraytirish (Esc)' : "Kattalashtirish (ikki marta bosish)"}
            className="rounded-[2px] border border-white/20 bg-black/60 p-1 text-white hover:bg-black/80"
          >
            {maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
          {editable && !maximized && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onRemove(index);
              }}
              aria-label="Katakdan olib tashlash"
              title="Katakdan olib tashlash"
              className="rounded-[2px] border border-white/20 bg-black/60 p-1 text-white hover:bg-danger"
            >
              <X size={13} />
            </button>
          )}
        </div>
      )}

      {selected && !maximized && (
        <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 z-20 w-0.5 bg-primary" />
      )}

      {maximized && camera && ptzAvailable && (
        <PtzControls key={camera.id} cameraId={camera.id} globalKeyboard className="absolute bottom-3 right-3 z-30" />
      )}
    </div>
  );
}
