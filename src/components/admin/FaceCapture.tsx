import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Camera, Check, RotateCcw } from 'lucide-react';
import { uploadFile } from '../../lib/fileUpload';
import { useAuth } from '../../lib/auth';

const OVAL_WIDTH_RATIO = 0.42;
const OVAL_HEIGHT_RATIO = 0.62;
const CAMERA_START_TIMEOUT_MS = 10_000;

class CameraTimeoutError extends Error {}

interface FaceCaptureProps {
  onConfirm: (faceDataUrl: string) => void;
}

export default function FaceCapture({ onConfirm }: FaceCaptureProps) {
  const { token } = useAuth();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [captured, setCaptured] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      setError(null);
      setReady(false);
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('getUserMedia unsupported');
        }

        // getUserMedia() can hang forever with no error and no permission
        // prompt when the OS itself is silently blocking camera access
        // (e.g. Windows' per-app camera consent entry in a stale/blank
        // state) — a real failure mode observed in testing, not a
        // hypothetical. Without this race, that leaves the user staring
        // at "Kamera ishga tushirilmoqda..." indefinitely with zero
        // feedback.
        const stream = await Promise.race([
          navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false,
          }),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new CameraTimeoutError()), CAMERA_START_TIMEOUT_MS),
          ),
        ]);
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setReady(true);
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof CameraTimeoutError
            ? "Kamera javob bermayapti. Windows sozlamalarida (Sozlamalar → Maxfiylik va xavfsizlik → Kamera) brauzerga ruxsat berilganini tekshiring, so'ng qayta urinib ko'ring"
            : err instanceof DOMException && err.name === 'NotAllowedError'
              ? 'Kameradan foydalanishga ruxsat berilmadi'
              : err instanceof DOMException && err.name === 'NotFoundError'
                ? 'Kamera topilmadi'
                : 'Kamerani ishga tushirib bo\'lmadi';
        setError(message);
      }
    }

    if (!captured) startCamera();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [captured]);

  async function handleCapture() {
    const video = videoRef.current;
    if (!video) return;

    const ovalW = video.videoWidth * OVAL_WIDTH_RATIO;
    const ovalH = video.videoHeight * OVAL_HEIGHT_RATIO;
    const x = (video.videoWidth - ovalW) / 2;
    const y = (video.videoHeight - ovalH) / 2;

    const canvas = document.createElement('canvas');
    canvas.width = ovalW;
    canvas.height = ovalH;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, x, y, ovalW, ovalH, 0, 0, ovalW, ovalH);

    streamRef.current?.getTracks().forEach((t) => t.stop());

    // Yuz solishtirish uchun mahalliy dataURL zudlik bilan ishlatiladi (ekranda
    // ko'rsatish + FaceMatchStep uchun) — real arxivlash MinIO'ga fon rejimida
    // amalga oshiriladi, muvaffaqiyatsiz bo'lsa ham enrollment jarayoni davom etadi.
    const dataUrl = canvas.toDataURL('image/png');
    setCaptured(dataUrl);

    canvas.toBlob((blob) => {
      if (!blob) return;
      uploadFile(blob, 'live-face-capture.png', token, 'face-captures').catch(() => {
        /* arxivlash muvaffaqiyatsiz — solishtirish jarayoniga ta'sir qilmaydi */
      });
    }, 'image/png');
  }

  function handleRetake() {
    setCaptured(null);
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl bg-red-50 dark:bg-red-500/10 p-6 text-center">
        <AlertTriangle size={24} className="text-red-500 dark:text-red-400" />
        <p className="text-sm font-semibold text-red-600 dark:text-red-400">{error}</p>
        <p className="text-xs text-red-400">
          Brauzer sozlamalaridan kamera ruxsatini bering va qayta urinib ko'ring
        </p>
        <button
          type="button"
          onClick={() => setError(null)}
          className="btn-glass flex items-center gap-1.5"
        >
          <RotateCcw size={14} />
          Qayta urinish
        </button>
      </div>
    );
  }

  if (captured) {
    return (
      <div className="flex flex-col items-center gap-4">
        <img
          src={captured}
          alt="Suratga olingan yuz"
          className="h-56 w-44 rounded-2xl border border-white/80 dark:border-white/10 object-cover shadow-btn"
        />
        <div className="flex gap-2">
          <button type="button" onClick={handleRetake} className="btn-glass flex items-center gap-1.5">
            <RotateCcw size={14} />
            Qayta suratga olish
          </button>
          <button
            type="button"
            onClick={() => onConfirm(captured)}
            className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700"
          >
            <Check size={14} />
            Tasdiqlash
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative aspect-[4/3] w-full max-w-sm overflow-hidden rounded-2xl bg-slate-900">
        <video ref={videoRef} muted playsInline className="h-full w-full object-cover" />
        {ready && (
          <div
            className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-dashed border-emerald-400/90"
            style={{ width: `${OVAL_WIDTH_RATIO * 100}%`, height: `${OVAL_HEIGHT_RATIO * 100}%` }}
          />
        )}
        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-xs font-medium text-white/70">
            Kamera ishga tushirilmoqda...
          </div>
        )}
      </div>
      <p className="text-center text-xs text-slate-500 dark:text-slate-400">
        Yuzingizni oval ichiga joylashtiring va yorug' joyda turing, so'ng suratga oling
      </p>
      <button
        type="button"
        onClick={handleCapture}
        disabled={!ready}
        className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Camera size={16} />
        Yuzni suratga olish
      </button>
    </div>
  );
}
