import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Camera, Check, RotateCcw } from 'lucide-react';
import { Button } from '../../ui';

const OVAL_WIDTH_RATIO = 0.42;
const OVAL_HEIGHT_RATIO = 0.62;
const CAMERA_START_TIMEOUT_MS = 10_000;

class CameraTimeoutError extends Error {}

interface FaceCaptureProps {
  onConfirm: (faceDataUrl: string) => void;
}

export default function FaceCapture({ onConfirm }: FaceCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [captured, setCaptured] = useState<string | null>(null);
  // "Qayta urinish" kamerani qaytadan ishga tushirishi uchun.
  const [attempt, setAttempt] = useState(0);

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
        const request = navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        });
        let timer: ReturnType<typeof setTimeout> | undefined;
        let timedOut = false;
        // Kutish muddati tugagach ruxsat berilsa ham kamera yonib qolmasin:
        // kechikib kelgan oqim darhol to'xtatiladi.
        request.then((late) => {
          if (timedOut || cancelled) late.getTracks().forEach((t) => t.stop());
        }).catch(() => undefined);
        const stream = await Promise.race([
          request,
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => {
              timedOut = true;
              reject(new CameraTimeoutError());
            }, CAMERA_START_TIMEOUT_MS);
          }),
        ]).finally(() => clearTimeout(timer));
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
            ? "Kamera javob bermayapti — tizim sozlamalarida ruxsatni tekshiring"
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
  }, [captured, attempt]);

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

    // Surat faqat brauzerda ishlatiladi (ekranda ko'rsatish + FaceMatchStep).
    // Omborga alohida yuklanmaydi: ilgari har bir urinish "face-captures/"
    // ga tushib, hech qaysi yozuvga bog'lanmay qolardi. Saqlanadigan yuz —
    // solishtiruvdan o'tgani, /api/students-staff/{id}/biometrics orqali.
    const dataUrl = canvas.toDataURL('image/png');
    setCaptured(dataUrl);
  }

  function handleRetake() {
    setCaptured(null);
  }

  if (error) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-card border border-danger/25 bg-danger-soft p-6 text-center">
        <AlertTriangle size={24} className="text-danger" aria-hidden="true" />
        <p className="text-sm font-semibold text-fg">{error}</p>
        <p className="text-xs text-muted">Brauzer sozlamalaridan kamera ruxsatini bering va qayta urinib ko&apos;ring</p>
        <Button
          size="sm"
          icon={RotateCcw}
          onClick={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        >
          Qayta urinish
        </Button>
      </div>
    );
  }

  if (captured) {
    return (
      <div className="flex flex-col items-center gap-4">
        <img src={captured} alt="Suratga olingan yuz" className="h-56 w-44 rounded-card border border-border object-cover shadow-card" />
        <div className="flex flex-wrap justify-center gap-2">
          <Button icon={RotateCcw} onClick={handleRetake}>
            Qayta suratga olish
          </Button>
          <Button variant="primary" icon={Check} onClick={() => onConfirm(captured)}>
            Tasdiqlash
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative aspect-[4/3] w-full max-w-sm overflow-hidden rounded-card bg-black">
        <video ref={videoRef} muted playsInline className="h-full w-full object-cover" />
        {ready && (
          <div
            className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-dashed border-success"
            style={{ width: `${OVAL_WIDTH_RATIO * 100}%`, height: `${OVAL_HEIGHT_RATIO * 100}%` }}
          />
        )}
        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-xs font-medium text-white/70">
            Kamera ishga tushirilmoqda...
          </div>
        )}
      </div>
      <p className="text-center text-xs text-muted">
        Yuzingizni oval ichiga joylashtiring va yorug' joyda turing, so'ng suratga oling
      </p>
      <Button variant="primary" icon={Camera} onClick={handleCapture} disabled={!ready}>
        Yuzni suratga olish
      </Button>
    </div>
  );
}
