import { useEffect, useRef, useState } from 'react';
import type Hls from 'hls.js';
import { Loader2, VideoOff } from 'lucide-react';
import FaceDetectionOverlay from './FaceDetectionOverlay';
import ZoneOverlay from './ZoneOverlay';
import { useLiveDetection } from '../lib/useLiveDetection';
import { acquireStreamSlot, releaseStreamSlot } from '../lib/streamLoadQueue';

interface LiveVideoPlayerProps {
  /**
   * Backend video-gateway tomonidan beriladigan HLS (.m3u8) yoki MP4/WebM manzil.
   * Bo'sh bo'lsa — hech narsa render qilinmaydi, chaqiruvchi komponent o'z
   * placeholder/status ko'rinishini (masalan "OFLAYN") ko'rsatishda davom etadi.
   * Bu — RTSP kamera → brauzer video oqimi integratsiyasi uchun asosiy ulanish nuqtasi:
   * backend RTSP oqimini WebRTC yoki HLS transkodlash orqali shu manzilga aylantirishi kerak.
   */
  streamUrl?: string;
  className?: string;
  /** Grid'da parallel HLS yukini kamaytirish — ms kechikish (navbat bilan) */
  startDelayMs?: number;
  /** Modal/yakka player — navbat cheklovisiz */
  priority?: boolean;
  /** Berilsa (va showDetections true bo'lsa), video ustiga yuz aniqlash
   * chegara chizig'ini (ism/uxlash holati bilan) chizadi — har bir aniq
   * kamerani kuzatib turgan foydalanuvchi uchun AI nima ko'rayotganini
   * jonli ko'rsatadi. Har poll — backendda haqiqiy kadr olish + aniqlash,
   * shuning uchun faqat foydalanuvchi shu kamerani ochib qo'yganida
   * yoqiladi (showDetections), doim emas. */
  cameraId?: string;
  showDetections?: boolean;
  /** Berilsa, video ustiga bosish orqali taqiqlangan zona ko'pburchagini
   * chizish rejimi yoqiladi (CameraZoneModal.tsx) — koordinatalar
   * app/models/camera.py's restricted_zone_polygon bilan bir xil formatda
   * (0-1 normallashtirilgan) qaytariladi. */
  zoneEditing?: boolean;
  zonePoints?: [number, number][];
  onZonePointAdd?: (point: [number, number]) => void;
}

const LOAD_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 6;

export default function LiveVideoPlayer({
  streamUrl,
  className = '',
  startDelayMs = 0,
  priority = false,
  cameraId,
  showDetections = false,
  zoneEditing = false,
  zonePoints = [],
  onZonePointAdd,
}: LiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const retriesRef = useRef(0);
  const detection = useLiveDetection(cameraId, showDetections && !error);

  useEffect(() => {
    setError(false);
    setLoading(true);
    retriesRef.current = 0;
    const video = videoRef.current;
    if (!video || !streamUrl) return;

    let cancelled = false;
    let hlsInstance: Hls | null = null;
    let loadTimer: ReturnType<typeof setTimeout> | null = null;
    let startTimer: ReturnType<typeof setTimeout> | null = null;

    function markReady() {
      if (!cancelled) setLoading(false);
    }

    function markFailed() {
      if (!cancelled) {
        setLoading(false);
        setError(true);
      }
    }

    async function attach() {
      if (!video) return;
      const isHls = streamUrl!.endsWith('.m3u8');

      loadTimer = setTimeout(() => {
        if (cancelled) return;
        if (video.videoWidth === 0) markFailed();
      }, LOAD_TIMEOUT_MS);

      if (isHls && !video.canPlayType('application/vnd.apple.mpegurl')) {
        const { default: HlsLib } = await import('hls.js');
        if (cancelled) return;
        if (!HlsLib.isSupported()) {
          markFailed();
          return;
        }

        hlsInstance = new HlsLib({
          enableWorker: true,
          lowLatencyMode: false,
          liveSyncDurationCount: 3,
          liveMaxLatencyDurationCount: 6,
          maxLiveSyncPlaybackRate: 1.5,
          backBufferLength: 0,
          maxBufferLength: 8,
          maxMaxBufferLength: 16,
          fragLoadingMaxRetry: 8,
          manifestLoadingMaxRetry: 6,
          levelLoadingMaxRetry: 6,
        });
        hlsInstance.loadSource(streamUrl!);
        hlsInstance.attachMedia(video);
        hlsInstance.on(HlsLib.Events.MANIFEST_PARSED, markReady);
        hlsInstance.on(HlsLib.Events.FRAG_BUFFERED, () => {
          if (video.videoWidth > 0) markReady();
        });
        hlsInstance.on(HlsLib.Events.ERROR, (_event, data) => {
          const code = data.response?.code;
          const retryableNetwork =
            data.type === HlsLib.ErrorTypes.NETWORK_ERROR &&
            (code === 404 || code === 401 || code === 500 || code === 0);
          if (!data.fatal && !retryableNetwork) return;
          if (retryableNetwork && retriesRef.current < MAX_RETRIES) {
            retriesRef.current += 1;
            hlsInstance?.startLoad(-1);
            return;
          }
          if (data.type === HlsLib.ErrorTypes.MEDIA_ERROR && retriesRef.current < MAX_RETRIES) {
            retriesRef.current += 1;
            hlsInstance?.recoverMediaError();
            return;
          }
          markFailed();
        });
      } else {
        video.src = streamUrl!;
        video.addEventListener('loadeddata', markReady, { once: true });
      }

      video.addEventListener(
        'playing',
        () => {
          if (video.videoWidth > 0) markReady();
        },
        { once: true },
      );

      try {
        await video.play();
      } catch {
        // Avtomatik ijro brauzer siyosati bilan bloklangan bo'lishi mumkin
      }
    }

    let slotHeld = false;

    async function start() {
      if (!priority) {
        await acquireStreamSlot();
        // If unmount/dep-change happened while we were queued, the effect's
        // cleanup already ran (with slotHeld still false, so it couldn't
        // release this slot) — release it here ourselves, or it leaks
        // permanently. With MAX_CONCURRENT=4 in streamLoadQueue.ts, a
        // handful of leaked slots is enough to wedge every video player on
        // the page until a full reload.
        if (cancelled) {
          releaseStreamSlot();
          return;
        }
        slotHeld = true;
      }
      await attach();
    }

    startTimer = setTimeout(() => {
      if (!cancelled) void start();
    }, startDelayMs);

    return () => {
      cancelled = true;
      if (startTimer) clearTimeout(startTimer);
      if (loadTimer) clearTimeout(loadTimer);
      hlsInstance?.destroy();
      video.removeAttribute('src');
      video.load();
      if (slotHeld) releaseStreamSlot();
    };
  }, [streamUrl, startDelayMs, priority]);

  if (!streamUrl) return null;

  if (error) {
    return (
      <div className={`absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-white/60 ${className}`}>
        <VideoOff size={20} />
        <span className="text-[11px] font-medium">Video oqimini yuklab bo&apos;lmadi</span>
      </div>
    );
  }

  return (
    <>
      {loading && (
        <div className="absolute inset-0 z-[1] flex items-center justify-center bg-slate-900/80">
          <Loader2 size={22} className="animate-spin text-slate-400" />
        </div>
      )}
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={`absolute inset-0 h-full w-full object-cover ${className}`}
      />
      {showDetections && <FaceDetectionOverlay videoRef={videoRef} detection={detection.result} />}
      {showDetections && detection.slotDenied && (
        <div className="absolute inset-x-0 bottom-0 bg-black/60 px-2 py-1 text-center text-[10px] font-medium text-amber-200">
          Boshqa kamerada AI ko&apos;rsatkich yoqilgan — navbatda
        </div>
      )}
      {zoneEditing && (
        <ZoneOverlay videoRef={videoRef} points={zonePoints} editable onAddPoint={onZonePointAdd} />
      )}
    </>
  );
}
