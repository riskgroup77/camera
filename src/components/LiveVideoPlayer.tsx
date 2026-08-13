import { useEffect, useRef, useState } from 'react';
import type Hls from 'hls.js';
import { VideoOff } from 'lucide-react';
import FaceDetectionOverlay from './FaceDetectionOverlay';
import ZoneOverlay from './ZoneOverlay';
import { useLiveDetection } from '../lib/useLiveDetection';

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

export default function LiveVideoPlayer({
  streamUrl,
  className = '',
  cameraId,
  showDetections = false,
  zoneEditing = false,
  zonePoints = [],
  onZonePointAdd,
}: LiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);
  const detection = useLiveDetection(cameraId, showDetections && !error);

  useEffect(() => {
    setError(false);
    const video = videoRef.current;
    if (!video || !streamUrl) return;

    let cancelled = false;
    let hlsInstance: Hls | null = null;

    async function attach() {
      if (!video) return;
      const isHls = streamUrl!.endsWith('.m3u8');

      if (isHls && !video.canPlayType('application/vnd.apple.mpegurl')) {
        const { default: HlsLib } = await import('hls.js');
        if (cancelled) return;
        if (HlsLib.isSupported()) {
          hlsInstance = new HlsLib();
          hlsInstance.loadSource(streamUrl!);
          hlsInstance.attachMedia(video);
          hlsInstance.on(HlsLib.Events.ERROR, (_event, data) => {
            if (data.fatal) setError(true);
          });
        } else {
          setError(true);
          return;
        }
      } else {
        video.src = streamUrl!;
      }

      try {
        await video.play();
      } catch {
        // Avtomatik ijro brauzer siyosati bilan bloklangan bo'lishi mumkin — bu xato emas
      }
    }

    attach();

    return () => {
      cancelled = true;
      hlsInstance?.destroy();
      video.removeAttribute('src');
      video.load();
    };
  }, [streamUrl]);

  if (!streamUrl) return null;

  if (error) {
    return (
      <div className={`absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-white/60 ${className}`}>
        <VideoOff size={20} />
        <span className="text-[11px] font-medium">Video oqimini yuklab bo'lmadi</span>
      </div>
    );
  }

  return (
    <>
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={`absolute inset-0 h-full w-full object-cover ${className}`}
      />
      {showDetections && <FaceDetectionOverlay videoRef={videoRef} detection={detection} />}
      {zoneEditing && (
        <ZoneOverlay videoRef={videoRef} points={zonePoints} editable onAddPoint={onZonePointAdd} />
      )}
    </>
  );
}
