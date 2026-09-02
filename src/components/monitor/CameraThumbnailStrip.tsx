import { Circle, Loader2 } from 'lucide-react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import Pagination from '../Pagination';
import { acquireThumbnailSlot, releaseThumbnailSlot } from '../../lib/monitorThumbnailQueue';
import type { CameraFeed } from '../../types';

const THUMBS_PER_PAGE = 8;
// MainCameraView's stream starts unthrottled at delay 0 — thumbnails
// start no earlier than this, so the main camera's connection is always
// genuinely underway before any thumbnail even attempts one, instead of
// all ~9 streams racing for bandwidth from the same instant. See
// monitorThumbnailQueue.ts for why they also go through their own
// (smaller-than-8) concurrency-limited queue on top of this.
const MAIN_CAMERA_HEAD_START_MS = 600;
const THUMBNAIL_STAGGER_MS = 200;

function ThumbnailCard({
  camera,
  active,
  onClick,
  streamStartDelayMs,
}: {
  camera: CameraFeed;
  active: boolean;
  onClick: () => void;
  streamStartDelayMs: number;
}) {
  const isLive = camera.status === 'live';
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active}
      className={`group relative aspect-video overflow-hidden rounded-xl bg-slate-900 text-left transition-all ${
        active
          ? 'ring-2 ring-indigo-500 ring-offset-2 ring-offset-white dark:ring-offset-slate-900'
          : 'ring-1 ring-white/10 hover:ring-indigo-300'
      }`}
    >
      {isLive && (
        <LiveVideoPlayer
          streamUrl={camera.streamUrl}
          startDelayMs={streamStartDelayMs}
          acquireSlot={acquireThumbnailSlot}
          releaseSlot={releaseThumbnailSlot}
        />
      )}
      {isLive ? (
        <span className="absolute left-1.5 top-1.5 z-10 flex items-center gap-1 rounded-full bg-emerald-500/90 px-1.5 py-0.5 text-[9px] font-bold text-white">
          <Circle size={5} className="fill-white" />
          JONLI
        </span>
      ) : (
        <span className="absolute left-1.5 top-1.5 z-10 rounded-full bg-slate-700 px-1.5 py-0.5 text-[9px] font-bold text-slate-300">
          OFLAYN
        </span>
      )}
      <span className="absolute inset-x-0 bottom-0 z-10 truncate bg-gradient-to-t from-black/80 to-transparent px-1.5 pb-1 pt-3 text-[10.5px] font-semibold text-white">
        {camera.name}
      </span>
    </button>
  );
}

/** Asosiy kamera tagidagi 8 talik kichik kameralar paneli — birortasini
 * bosish uni asosiy ko'rinishga o'tkazadi (MonitoringPage'dagi
 * activeCamera holatini almashtiradi orqali). */
export default function CameraThumbnailStrip({
  cameras,
  activeId,
  onSelect,
  page,
  totalPages,
  total,
  onPageChange,
  loading,
}: {
  cameras: CameraFeed[];
  activeId: string | null;
  onSelect: (camera: CameraFeed) => void;
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
  loading: boolean;
}) {
  return (
    <div>
      {loading && cameras.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-slate-400">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : cameras.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 py-8 text-center text-xs text-slate-400 dark:border-white/10 dark:text-slate-500">
          Kamera topilmadi
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {cameras.map((camera, index) => (
            <ThumbnailCard
              key={camera.id}
              camera={camera}
              active={camera.id === activeId}
              onClick={() => onSelect(camera)}
              streamStartDelayMs={MAIN_CAMERA_HEAD_START_MS + Math.min(index, THUMBS_PER_PAGE) * THUMBNAIL_STAGGER_MS}
            />
          ))}
        </div>
      )}

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={THUMBS_PER_PAGE} onChange={onPageChange} />
    </div>
  );
}

export { THUMBS_PER_PAGE };
