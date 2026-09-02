import { useEffect, useState } from 'react';
import { Building2, Circle, Expand, MapPin, Minimize2, Sparkles, VideoOff } from 'lucide-react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import { useCameraAnalysisStatus } from '../../lib/useCameraAnalysisStatus';
import { formatModules, formatSecondsAgo } from '../../lib/formatAnalysis';
import type { CameraFeed } from '../../types';

/** Katta, asosiy kamera ko'rinishi — CameraThumbnailStrip'dan tanlangan
 * kamerani shu yerda ko'rsatadi. CameraDetailModal bilan bir xil
 * video/overlay tarkibi, faqat modal emas, sahifaning o'zida joylashgan. */
export default function MainCameraView({ camera }: { camera: CameraFeed | null }) {
  const [fullscreen, setFullscreen] = useState(false);
  const isLive = camera?.status === 'live';
  const analysis = useCameraAnalysisStatus(camera?.id, !!camera && isLive);

  useEffect(() => {
    setFullscreen(false);
  }, [camera?.id]);

  return (
    <div
      className={`relative flex aspect-video items-center justify-center overflow-hidden rounded-2xl bg-slate-900 transition-all ${
        fullscreen ? 'fixed inset-4 z-[60] aspect-auto' : ''
      }`}
    >
      {!camera && (
        <div className="flex flex-col items-center gap-1.5 text-white/40">
          <VideoOff size={28} />
          <span className="text-sm font-medium">Kamera tanlanmagan</span>
        </div>
      )}

      {camera && isLive && (
        <LiveVideoPlayer streamUrl={camera.streamUrl} cameraId={camera.id} showDetections priority />
      )}

      {camera && (
        <>
          {isLive ? (
            <>
              <span className="absolute left-3 top-3 z-10 flex items-center gap-1 rounded-full bg-emerald-500/90 px-2.5 py-1 text-xs font-bold text-white">
                <Circle size={7} className="fill-white" />
                JONLI
              </span>
              <span className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-full bg-red-500/90 px-2.5 py-1 text-xs font-bold text-white">
                REC
              </span>
            </>
          ) : (
            <span className="absolute left-3 top-3 z-10 rounded-full bg-slate-700 px-3 py-1 text-xs font-bold text-slate-300">
              OFLAYN
            </span>
          )}

          <span className="absolute bottom-3 left-3 z-10 rounded-lg bg-black/55 px-2.5 py-1.5 text-xs font-semibold text-white">
            {camera.name}
          </span>

          {isLive && analysis && (
            <div className="absolute bottom-12 left-3 right-3 z-10 flex items-start gap-1.5 rounded-lg bg-black/65 px-2.5 py-1.5 text-[11px] font-medium text-white">
              <Sparkles size={12} className="mt-0.5 shrink-0 text-amber-300" />
              <span>
                Fon AI: {formatSecondsAgo(analysis.secondsAgo)}
                {analysis.faceCount > 0 ? ` · ${analysis.faceCount} yuz` : ''}
                {analysis.modules.length ? ` · ${formatModules(analysis.modules)}` : ''}
                {analysis.eventsRaised > 0 ? ` · ${analysis.eventsRaised} hodisa` : ''}
              </span>
            </div>
          )}

          <button
            onClick={() => setFullscreen((v) => !v)}
            className="absolute bottom-3 right-3 z-10 flex items-center gap-1 rounded-lg bg-black/50 px-2 py-1 text-xs font-semibold text-white transition-colors hover:bg-black/70"
          >
            {fullscreen ? <Minimize2 size={13} /> : <Expand size={13} />}
            {fullscreen ? "Yig'ish" : "To'liq ekran"}
          </button>
        </>
      )}

      {camera && (
        <div className="absolute left-3 top-11 z-10 flex flex-col gap-1 text-[11px] text-white/80">
          <span className="flex items-center gap-1 rounded-lg bg-black/45 px-2 py-1">
            <Building2 size={11} />
            {camera.building}
          </span>
          <span className="flex items-center gap-1 rounded-lg bg-black/45 px-2 py-1">
            <MapPin size={11} />
            {camera.zone}
          </span>
        </div>
      )}
    </div>
  );
}
