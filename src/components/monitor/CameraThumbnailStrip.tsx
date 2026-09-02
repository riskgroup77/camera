import { Circle, Loader2 } from 'lucide-react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import Pagination from '../Pagination';
import type { CameraFeed } from '../../types';

const THUMBS_PER_PAGE = 8;

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
      {/* priority: bypasses streamLoadQueue's shared MAX_CONCURRENT=8 gate
          (src/lib/streamLoadQueue.ts) — that queue exists for grids that can
          show far more than 8 cards at once (VirtualCameraGrid's scroll
          mode), where letting every card connect immediately would open way
          too many concurrent HLS streams. This strip never shows more than
          THUMBS_PER_PAGE (8) at a time, plus MainCameraView's own one
          priority stream, so there's no reason for any of them to sit
          waiting for a turn — every visible thumbnail should load fully,
          right away. A small startDelayMs stagger still avoids firing all
          the connection requests in the exact same tick. */}
      {isLive && (
        <LiveVideoPlayer streamUrl={camera.streamUrl} startDelayMs={streamStartDelayMs} priority />
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
              streamStartDelayMs={Math.min(index, THUMBS_PER_PAGE) * 150}
            />
          ))}
        </div>
      )}

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={THUMBS_PER_PAGE} onChange={onPageChange} />
    </div>
  );
}

export { THUMBS_PER_PAGE };
