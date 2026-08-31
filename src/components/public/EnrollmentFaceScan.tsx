import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Camera, RotateCcw } from 'lucide-react';

const OVAL_WIDTH_RATIO = 0.42;
const OVAL_HEIGHT_RATIO = 0.62;
const CAMERA_START_TIMEOUT_MS = 10_000;

class CameraTimeoutError extends Error {}

// Uch burchak yetarli: to'g'ridan (asosiy saqlanadigan rasm) + ikki yon
// burilish — bu kamera tomonidan turli burchaklardan tanib olishni
// yaxshilaydi, backend esa har bir kadrni bir xil odamga tegishli
// ekanligini avtomatik tekshiradi (app/services/face_recognition.py
// extract_enrollment_embedding). Birinchi kadr har doim to'g'ridan bo'lishi
// kerak — backend uni saqlanadigan profil rasmi sifatida ishlatadi.
const POSES = [
  { label: "To'g'riga qarang", hint: 'Kamera bilan yuzma-yuz turing' },
  { label: 'Boshingizni chapga buring', hint: "Sekin, ~30 daraja" },
  { label: 'Boshingizni o\'ngga buring', hint: "Sekin, ~30 daraja" },
] as const;

interface EnrollmentFaceScanProps {
  onComplete: (frames: Blob[]) => void;
}

export default function EnrollmentFaceScan({ onComplete }: EnrollmentFaceScanProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [step, setStep] = useState(0);
  const [frames, setFrames] = useState<Blob[]>([]);
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      setError(null);
      setReady(false);
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('getUserMedia unsupported');
        }
        const stream = await Promise.race([
          navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false,
          }),
          new Promise<never>((_, reject) => setTimeout(() => reject(new CameraTimeoutError()), CAMERA_START_TIMEOUT_MS)),
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
            ? "Kamera javob bermayapti. Brauzer sozlamalarida kameraga ruxsat berilganini tekshiring"
            : err instanceof DOMException && err.name === 'NotAllowedError'
              ? 'Kameradan foydalanishga ruxsat berilmadi'
              : err instanceof DOMException && err.name === 'NotFoundError'
                ? 'Kamera topilmadi'
                : "Kamerani ishga tushirib bo'lmadi";
        setError(message);
      }
    }

    startCamera();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  async function handleCapture() {
    const video = videoRef.current;
    if (!video || capturing) return;
    setCapturing(true);

    const ovalW = video.videoWidth * OVAL_WIDTH_RATIO;
    const ovalH = video.videoHeight * OVAL_HEIGHT_RATIO;
    const x = (video.videoWidth - ovalW) / 2;
    const y = (video.videoHeight - ovalH) / 2;

    const canvas = document.createElement('canvas');
    canvas.width = ovalW;
    canvas.height = ovalH;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setCapturing(false);
      return;
    }
    ctx.drawImage(video, x, y, ovalW, ovalH, 0, 0, ovalW, ovalH);

    canvas.toBlob(
      (blob) => {
        setCapturing(false);
        if (!blob) return;
        const nextFrames = [...frames, blob];
        setFrames(nextFrames);
        if (step + 1 < POSES.length) {
          setStep(step + 1);
        } else {
          streamRef.current?.getTracks().forEach((t) => t.stop());
          onComplete(nextFrames);
        }
      },
      'image/jpeg',
      0.92,
    );
  }

  function handleRestart() {
    setFrames([]);
    setStep(0);
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl bg-red-50 dark:bg-red-500/10 p-6 text-center">
        <AlertTriangle size={24} className="text-red-500 dark:text-red-400" />
        <p className="text-sm font-semibold text-red-600 dark:text-red-400">{error}</p>
        <button type="button" onClick={() => setError(null)} className="btn-glass flex items-center gap-1.5">
          <RotateCcw size={14} />
          Qayta urinish
        </button>
      </div>
    );
  }

  const pose = POSES[step];

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="flex items-center gap-1.5">
        {POSES.map((p, i) => (
          <span
            key={p.label}
            className={`h-1.5 w-8 rounded-full transition-colors ${
              i < step ? 'bg-emerald-500' : i === step ? 'bg-indigo-500' : 'bg-slate-200 dark:bg-white/10'
            }`}
          />
        ))}
      </div>

      <div className="relative aspect-[4/3] w-full max-w-sm overflow-hidden rounded-2xl bg-slate-900">
        <video ref={videoRef} muted playsInline className="h-full w-full -scale-x-100 object-cover" />
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

      <div className="text-center">
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{pose.label}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{pose.hint}</p>
        <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
          {step + 1}-qadam / {POSES.length}
        </p>
      </div>

      <div className="flex gap-2">
        {frames.length > 0 && (
          <button type="button" onClick={handleRestart} className="btn-glass flex items-center gap-1.5">
            <RotateCcw size={14} />
            Boshidan
          </button>
        )}
        <button
          type="button"
          onClick={handleCapture}
          disabled={!ready || capturing}
          className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Camera size={16} />
          Suratga olish
        </button>
      </div>
    </div>
  );
}
