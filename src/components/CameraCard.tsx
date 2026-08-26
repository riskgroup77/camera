import { Circle, MapPin, Video } from 'lucide-react';
import LiveVideoPlayer from './LiveVideoPlayer';
import type { CameraFeed } from '../types';

export default function CameraCard({
  camera,
  onClick,
  playStream = true,
}: {
  camera: CameraFeed;
  onClick?: () => void;
  /** false = placeholder (virtual grid — HLS oqimi ochilmaydi) */
  playStream?: boolean;
}) {
  const isLive = camera.status === 'live';

  return (
    <div
      onClick={onClick}
      className="glass flex cursor-pointer flex-col gap-2.5 p-4 transition-transform hover:-translate-y-0.5 hover:shadow-lg"
    >
      <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl bg-slate-900">
        {/* Detection (yuz chegarasi) faqat CameraDetailModal'da yoqiladi (onClick orqali
            ochiladi) — grid'da 30 tagacha kartochka bir vaqtda ko'rinishi mumkin, har biri
            showDetections bilan har 6s'da live-detection so'rovi yuborsa, bu fon AI
            sweep'lari (davomat, uxlab qolish) bilan bir xil inference navbatini band qilardi. */}
        {isLive && playStream && <LiveVideoPlayer streamUrl={camera.streamUrl} cameraId={camera.id} />}
        {isLive && !playStream && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-slate-800/90 text-slate-400">
            <Video size={22} className="opacity-60" />
            <span className="text-[10px] font-medium">Ko&apos;rinishda emas</span>
          </div>
        )}
        {isLive ? (
          <>
            <span className="absolute left-2 top-2 flex items-center gap-1 rounded-full bg-emerald-500/90 px-2 py-0.5 text-[10px] font-bold text-white">
              <Circle size={6} className="fill-white" />
              JONLI
            </span>
            <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-red-500/90 px-2 py-0.5 text-[10px] font-bold text-white">
              REC
            </span>
          </>
        ) : (
          <span className="rounded-full bg-slate-700 px-2 py-0.5 text-[10px] font-bold text-slate-300">
            OFLAYN
          </span>
        )}
      </div>

      <div>
        <p className="text-sm font-bold text-slate-900 dark:text-slate-100">{camera.name}</p>
        <p className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <MapPin size={11} />
          {camera.building} · {camera.zone}
        </p>
      </div>
    </div>
  );
}
