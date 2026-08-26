import { useEffect, useState } from 'react';
import { Building2, Circle, Expand, Eye, EyeOff, MapPin, Minimize2 } from 'lucide-react';
import Modal from './Modal';
import LiveVideoPlayer from './LiveVideoPlayer';
import type { CameraFeed } from '../types';

export default function CameraDetailModal({
  camera,
  onClose,
}: {
  camera: CameraFeed | null;
  onClose: () => void;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const [showDetections, setShowDetections] = useState(false);
  const isLive = camera?.status === 'live';

  useEffect(() => {
    setShowDetections(false);
  }, [camera?.id]);

  return (
    <Modal open={!!camera} onClose={onClose} title={camera?.name} maxWidth="max-w-2xl">
      {camera && (
        <div className="space-y-5">
          <div
            className={`relative flex items-center justify-center overflow-hidden rounded-2xl bg-slate-900 transition-all ${
              fullscreen ? 'fixed inset-4 z-[60] rounded-2xl' : 'aspect-video'
            }`}
          >
            {isLive && (
              <LiveVideoPlayer
                streamUrl={camera.streamUrl}
                cameraId={camera.id}
                showDetections={showDetections}
              />
            )}
            {isLive ? (
              <>
                <span className="absolute left-3 top-3 flex items-center gap-1 rounded-full bg-emerald-500/90 px-2.5 py-1 text-xs font-bold text-white">
                  <Circle size={7} className="fill-white" />
                  JONLI
                </span>
                <span className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-red-500/90 px-2.5 py-1 text-xs font-bold text-white">
                  REC
                </span>
              </>
            ) : (
              <span className="rounded-full bg-slate-700 px-3 py-1 text-xs font-bold text-slate-300">
                OFLAYN
              </span>
            )}
            <button
              onClick={() => setShowDetections((v) => !v)}
              className="absolute bottom-3 left-3 flex items-center gap-1 rounded-lg bg-black/50 px-2 py-1 text-xs font-semibold text-white transition-colors hover:bg-black/70"
            >
              {showDetections ? <EyeOff size={13} /> : <Eye size={13} />}
              {showDetections ? 'AI o\'chirish' : 'AI ko\'rsatkich'}
            </button>
            <button
              onClick={() => setFullscreen((v) => !v)}
              className="absolute bottom-3 right-3 flex items-center gap-1 rounded-lg bg-black/50 px-2 py-1 text-xs font-semibold text-white transition-colors hover:bg-black/70"
            >
              {fullscreen ? <Minimize2 size={13} /> : <Expand size={13} />}
              {fullscreen ? "Yig'ish" : "To'liq ekran"}
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <InfoRow icon={<Building2 size={15} />} label="Bino" value={camera.building} />
            <InfoRow icon={<MapPin size={15} />} label="Zona" value={camera.zone} />
          </div>
        </div>
      )}
    </Modal>
  );
}

function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="glass-deep flex items-center gap-2.5 px-3 py-2.5">
      <span className="text-slate-400 dark:text-slate-500">{icon}</span>
      <div className="min-w-0">
        <p className="text-[11px] text-slate-400 dark:text-slate-500">{label}</p>
        <p className="truncate font-medium text-slate-800 dark:text-slate-200">{value}</p>
      </div>
    </div>
  );
}
