import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, RotateCcw, ScanFace, VideoOff } from 'lucide-react';
import { type LivenessStep, LIVENESS_STEPS, checkPose } from '../../lib/enrollment';

interface EnrollmentFaceCaptureProps {
  onSubmit: (frames: Blob[]) => void;
  submitting?: boolean;
  /** Serverdan kelgan xato — bosqichni qaytadan boshlash uchun. */
  externalError?: string | null;
}

/** Bosqichlarning ekrandagi ko'rinishi. */
const STEP_UI: Record<LivenessStep, { title: string; hint: string; arrow: string }> = {
  front: {
    title: "To'g'riga qarang",
    hint: 'Yuzingiz doira ichida to‘liq ko‘rinsin',
    arrow: '',
  },
  left: {
    title: 'Boshingizni chapga buring',
    hint: 'Sekin buring va shu holatda turing',
    arrow: '←',
  },
  right: {
    title: 'Boshingizni o‘ngga buring',
    hint: 'Sekin buring va shu holatda turing',
    arrow: '→',
  },
};

/** Serverga yuboriladigan yo‘naltirish kadrining kengligi.
 *
 *  Kichraytirish ataylab: bu kadr saqlanmaydi va faqat "hozir to‘g‘ri
 *  turibsizmi" degan savolga javob berish uchun ishlatiladi. To‘liq
 *  o‘lchamdagi kadrni sekundiga ikki marta yuborish tarmoqni ham,
 *  serverni ham bekorga yuklardi. */
const PROBE_WIDTH = 480;
const PROBE_INTERVAL_MS = 700;

/** Bosqich tasdiqlanishi uchun ketma-ket necha marta mos kelishi kerak.
 *  Bir lahzalik tasodifiy burilish hisobga olinmasligi uchun. */
const STABLE_HITS = 2;

/**
 * Kamera orqali tiriklik tekshiruvi bilan yuzni ro‘yxatdan o‘tkazish.
 *
 * Tayyor rasm yuklash o‘rniga keldi. Sabab dalilning kuchida: yuklangan
 * rasmni boshqa odamning rasmi bilan, telefon ekranidagi surat bilan
 * yoki qog‘ozga bosilgan fotosurat bilan almashtirib bo‘ladi. Boshni
 * burish bu hujumlarning katta qismini yopadi — statik rasm burilmaydi.
 *
 * Uch bosqich: to‘g‘riga qarash, chapga burilish, o‘ngga burilish. Har
 * bir bosqichda kadr serverga yuborilib, yuzning haqiqatan qaysi tomonga
 * qaragani tekshiriladi va foydalanuvchi ekranda darhol javob ko‘radi.
 *
 * Ko‘rinish oyna kabi teskari ko‘rsatiladi (odam o‘zini tabiiy ko‘rishi
 * uchun), lekin SERVERGA yuboriladigan kadr teskari qilinmaydi — aks
 * holda chap va o‘ng joy almashib qolardi.
 */
export default function EnrollmentFaceCapture({
  onSubmit,
  submitting = false,
  externalError = null,
}: EnrollmentFaceCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const framesRef = useRef<Blob[]>([]);
  const hitsRef = useRef(0);
  const busyRef = useRef(false);
  const doneRef = useRef(false);

  const [ready, setReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [hint, setHint] = useState('Kamera ishga tushmoqda...');
  const [matching, setMatching] = useState(false);
  const [captured, setCaptured] = useState<string[]>([]);

  const step = LIVENESS_STEPS[stepIndex];
  const finished = stepIndex >= LIVENESS_STEPS.length;

  // ─────────────────────────── Kamerani ochish
  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError(
          "Bu brauzer kameraga kirishni qo‘llab-quvvatlamaydi. Boshqa brauzerda oching.",
        );
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {
            /* avtomatik ijro bloklangan bo‘lsa foydalanuvchi bosadi */
          });
        }
        setReady(true);
        setHint('Yuzingiz doira ichida to‘liq ko‘rinsin');
      } catch (err) {
        const name = err instanceof DOMException ? err.name : '';
        setCameraError(
          name === 'NotAllowedError'
            ? 'Kameraga ruxsat berilmadi. Brauzer sozlamalaridan ruxsat bering va sahifani yangilang.'
            : name === 'NotFoundError'
              ? 'Kamera topilmadi. Kamerasi bor qurilmadan urinib ko‘ring.'
              : 'Kamerani ochib bo‘lmadi. Boshqa dastur uni band qilmaganini tekshiring.',
        );
      }
    }

    start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  // ─────────────────────────── Kadr olish
  const grab = useCallback((maxWidth?: number): Promise<Blob | null> => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return Promise.resolve(null);

    const scale = maxWidth ? Math.min(1, maxWidth / video.videoWidth) : 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return Promise.resolve(null);

    // Teskari qilinmaydi: ko‘rinish oyna kabi bo‘lsa ham, serverga
    // kameraning haqiqiy tasviri boradi.
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', maxWidth ? 0.65 : 0.9),
    );
  }, []);

  // ─────────────────────────── Jonli yo‘naltirish
  useEffect(() => {
    if (!ready || finished || cameraError || submitting) return;

    let stopped = false;
    const timer = window.setInterval(async () => {
      if (stopped || busyRef.current || doneRef.current) return;
      busyRef.current = true;
      try {
        const probe = await grab(PROBE_WIDTH);
        if (!probe || stopped) return;

        const result = await checkPose(step, probe);
        if (stopped) return;

        setHint(result.hint);
        setMatching(result.ok);

        if (!result.ok) {
          hitsRef.current = 0;
          return;
        }

        hitsRef.current += 1;
        if (hitsRef.current < STABLE_HITS) return;

        // Bosqich tasdiqlandi — endi TO‘LIQ o‘lchamdagi kadr olinadi.
        const full = await grab();
        if (!full || stopped) return;
        hitsRef.current = 0;
        framesRef.current = [...framesRef.current, full];
        setCaptured((prev) => [...prev, URL.createObjectURL(full)]);
        setMatching(false);
        setStepIndex((i) => i + 1);
      } catch {
        // Tarmoq uzilishi — keyingi urinishda davom etadi. Bu yerda
        // xato ko‘rsatish shovqin bo‘lardi: sekundiga bir marta
        // chaqiriladigan so‘rovning bittasi o‘tmasligi normal.
      } finally {
        busyRef.current = false;
      }
    }, PROBE_INTERVAL_MS);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [ready, finished, cameraError, submitting, step, grab]);

  // ─────────────────────────── Uch kadr yig‘ilgach yuborish
  useEffect(() => {
    if (!finished || doneRef.current || submitting) return;
    doneRef.current = true;
    onSubmit(framesRef.current);
  }, [finished, submitting, onSubmit]);

  // Serverdan xato kelsa boshidan boshlaymiz — qaysi kadr o‘tmaganini
  // bilmaymiz, va yarim to‘plam bilan davom etish noto‘g‘ri natija
  // beradi.
  useEffect(() => {
    if (!externalError) return;
    doneRef.current = false;
    hitsRef.current = 0;
    framesRef.current = [];
    setCaptured((prev) => {
      prev.forEach((url) => URL.revokeObjectURL(url));
      return [];
    });
    setStepIndex(0);
    setMatching(false);
  }, [externalError]);

  useEffect(
    () => () => {
      captured.forEach((url) => URL.revokeObjectURL(url));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  function restart() {
    doneRef.current = false;
    hitsRef.current = 0;
    framesRef.current = [];
    captured.forEach((url) => URL.revokeObjectURL(url));
    setCaptured([]);
    setStepIndex(0);
    setMatching(false);
  }

  // ─────────────────────────── Ko‘rinish
  if (cameraError) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-2 rounded-xl bg-red-50 p-4 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-400">
          <VideoOff size={18} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold">Kamera ochilmadi</p>
            <p className="mt-1 leading-relaxed">{cameraError}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="btn-glass flex items-center justify-center gap-1.5"
        >
          <RotateCcw size={15} />
          Qayta urinish
        </button>
      </div>
    );
  }

  const total = LIVENESS_STEPS.length;
  const ui = finished ? null : STEP_UI[step];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Yuzingizni kamera orqali tasdiqlang
        </p>
        <p className="mt-1 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          Uch bosqich: to&apos;g&apos;riga qarang, so&apos;ng boshingizni chapga va o&apos;ngga
          buring. Yorug&apos; joyda turing, ko&apos;zoynak va niqobni oling.
        </p>
      </div>

      {/* Doira ichidagi jonli tasvir */}
      <div className="relative mx-auto aspect-square w-full max-w-[300px]">
        <ProgressRing done={captured.length} total={total} active={matching} />

        <div
          className={`absolute inset-[9%] overflow-hidden rounded-full border-[3px] transition-colors duration-200 ${
            matching
              ? 'border-emerald-400'
              : finished
                ? 'border-emerald-500'
                : 'border-white/70 dark:border-white/20'
          }`}
        >
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            className="h-full w-full scale-x-[-1] object-cover"
          />
          {!ready && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-900/70 text-white">
              <ScanFace size={30} className="animate-pulse" />
            </div>
          )}
        </div>

        {/* Burilish yo'nalishi ko'rsatkichi */}
        {ui?.arrow && !matching && (
          <span
            className={`pointer-events-none absolute top-1/2 -translate-y-1/2 text-4xl font-bold text-indigo-400 ${
              step === 'left' ? 'left-0' : 'right-0'
            } animate-pulse`}
            aria-hidden
          >
            {ui.arrow}
          </span>
        )}
      </div>

      {/* Bosqich va maslahat */}
      <div className="text-center">
        {finished ? (
          <p className="flex items-center justify-center gap-1.5 text-sm font-bold text-emerald-600 dark:text-emerald-400">
            <Check size={16} />
            Uchala bosqich bajarildi
          </p>
        ) : (
          <>
            <p className="text-sm font-bold text-slate-900 dark:text-slate-100">
              {stepIndex + 1}/{total} — {ui?.title}
            </p>
            <p
              className={`mt-1 text-xs font-medium transition-colors ${
                matching ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {hint || ui?.hint}
            </p>
          </>
        )}
      </div>

      {/* Olingan kadrlar */}
      {captured.length > 0 && (
        <div className="flex items-center justify-center gap-2">
          {LIVENESS_STEPS.map((s, i) => (
            <div
              key={s}
              className={`h-14 w-14 overflow-hidden rounded-xl border-2 ${
                captured[i] ? 'border-emerald-400' : 'border-dashed border-slate-300 dark:border-white/15'
              }`}
            >
              {captured[i] ? (
                <img src={captured[i]} alt="" className="h-full w-full scale-x-[-1] object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400">
                  {i + 1}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {externalError && (
        <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{externalError} Bosqichlar boshidan boshlandi.</span>
        </div>
      )}

      {submitting && (
        <p className="text-center text-xs font-medium text-indigo-600 dark:text-indigo-400">
          Yuz saqlanmoqda...
        </p>
      )}

      {captured.length > 0 && !submitting && (
        <button
          type="button"
          onClick={restart}
          className="mx-auto flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
        >
          <RotateCcw size={13} />
          Boshidan boshlash
        </button>
      )}
    </div>
  );
}

/** Face ID uslubidagi halqa: har bir chiziqcha bosqich ulushini bildiradi. */
function ProgressRing({ done, total, active }: { done: number; total: number; active: boolean }) {
  const TICKS = 60;
  const filled = Math.round((done / total) * TICKS);

  return (
    <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden>
      {Array.from({ length: TICKS }, (_, i) => {
        const angle = (i / TICKS) * 360 - 90;
        const rad = (angle * Math.PI) / 180;
        const isDone = i < filled;
        // Joriy bosqich davomida keyingi bo'lakcha nafas oladi
        const isActive = active && i >= filled && i < filled + Math.round(TICKS / total);
        return (
          <line
            key={i}
            x1={50 + 44 * Math.cos(rad)}
            y1={50 + 44 * Math.sin(rad)}
            x2={50 + 49 * Math.cos(rad)}
            y2={50 + 49 * Math.sin(rad)}
            strokeWidth={1.6}
            strokeLinecap="round"
            className={
              isDone
                ? 'stroke-emerald-400'
                : isActive
                  ? 'stroke-indigo-400 animate-pulse'
                  : 'stroke-slate-300 dark:stroke-white/15'
            }
          />
        );
      })}
    </svg>
  );
}
