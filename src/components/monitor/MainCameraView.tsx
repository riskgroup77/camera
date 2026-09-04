import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Building2, Circle, Expand, MapPin, Minimize2, Sparkles, VideoOff } from 'lucide-react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import { useCameraAnalysisStatus } from '../../lib/useCameraAnalysisStatus';
import { formatModules, formatSecondsAgo } from '../../lib/formatAnalysis';
import type { CameraFeed } from '../../types';

/** Katta, asosiy kamera ko'rinishi — CameraThumbnailStrip'dan tanlangan
 * kamerani shu yerda ko'rsatadi. CameraDetailModal bilan bir xil
 * video/overlay tarkibi, faqat modal emas, sahifaning o'zida joylashgan.
 *
 * Qasddan aspect-video EMAS: butun "Video Monitoring Markazi" bloki bir
 * ekranga (scroll'siz) sig'ishi kerak bo'lgani uchun, bu komponent o'z
 * balandligini kenglikdan hisoblab chiqarish o'rniga MonitoringPage'dan
 * kelgan `className` (odatda flex-1) orqali qolgan bo'sh joyni egallaydi
 * — video elementning o'zi baribir object-cover bilan to'ldiriladi, shu
 * sababli nisbat qat'iy 16:9 bo'lmasa ham vizual jihatdan to'g'ri chiqadi. */
export default function MainCameraView({
  camera,
  className = '',
}: {
  camera: CameraFeed | null;
  className?: string;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const isLive = camera?.status === 'live';
  const analysis = useCameraAnalysisStatus(camera?.id, !!camera && isLive);

  useEffect(() => {
    setFullscreen(false);
  }, [camera?.id]);

  // Escape — to'liq ekrandan chiqish. Bu haqiqiy Fullscreen API emas,
  // oddiy qoplama, shuning uchun brauzer Escape'ni o'zi ushlamaydi va
  // usiz foydalanuvchi qoplamada qamalib qolishi mumkin edi.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  const body = (
    <div
      className={
        fullscreen
          ? 'fixed inset-4 z-[60] flex items-center justify-center overflow-hidden rounded-2xl bg-slate-900'
          : `relative flex items-center justify-center overflow-hidden rounded-2xl bg-slate-900 transition-all ${className}`
      }
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
          {isLive && camera.hasVideo === false ? (
            <span className="absolute left-3 top-3 z-10 rounded-full bg-amber-500/90 px-3 py-1 text-xs font-bold text-white">
              TASVIRSIZ — kamera javob beryapti, lekin video kelmayapti
            </span>
          ) : isLive ? (
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

  // To'liq ekran qoplamasi document.body'ga PORTAL orqali chiqariladi.
  //
  // Sababi nozik va uni faqat production'da ko'rib aniqladik: bu
  // komponentning ota elementi `.glass` klassiga ega, unda esa
  // `backdrop-blur` (ya'ni backdrop-filter) bor. CSS qoidasi bo'yicha
  // backdrop-filter qo'yilgan element o'zining ichidagi
  // `position: fixed` elementlar uchun yangi tayanch nuqta (containing
  // block) yaratadi — natijada `inset-4` ekranga emas, o'sha shisha
  // panelga nisbatan hisoblanardi va qoplama ko'rinmay qolardi, asosiy
  // joy esa (element oqimdan chiqqani uchun) bo'shab qolardi.
  //
  // Portal ota zanjirini butunlay chetlab o'tadi, shuning uchun
  // `fixed` yana ekranga nisbatan ishlaydi.
  if (fullscreen) {
    return (
      <>
        <div className={className} aria-hidden />
        {createPortal(body, document.body)}
      </>
    );
  }
  return body;
}
