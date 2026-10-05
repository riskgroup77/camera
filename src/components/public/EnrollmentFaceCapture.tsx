import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Loader2, RotateCcw, ScanFace, VideoOff } from 'lucide-react';
import { Button, CodeText, MicroLabel, StatusLamp, cn, type IntelStatus } from '../../ui';
import { Notice } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
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

/** Serverga SAQLASH uchun yuboriladigan kadrning eng katta kengligi.
 *
 *  Chegarasiz bo'lsa kadr kameraning o'z o'lchamida ketardi: `ideal:
 *  1280` faqat iltimos, majburiyat emas — 4K veb-kamera yoki zamonaviy
 *  telefon 3840px kadr beradi va bitta JPEG 2-3 MB ga chiqadi. Uchta
 *  kadr = 9 MB, mobil internetda esa bu bir necha daqiqalik kutish va
 *  serverda 413. Tanib olish uchun 1280px dan ortig'i baribir kerak
 *  emas — model kadrni o'zi kichraytiradi. */
const MAX_FRAME_WIDTH = 1280;
const FRAME_QUALITY = 0.85;

/** getUserMedia xatolari — sabablari butunlay boshqa, demak matni ham
 *  boshqa bo'lishi kerak. Nomlar brauzerlar bo'yicha farq qiladi
 *  (Firefox'da NotReadableError o'rniga TrackStartError, eski
 *  Chrome'da NotFoundError o'rniga DevicesNotFoundError). */
const CAMERA_ERRORS: Record<string, string> = {
  NotAllowedError:
    "Kameraga ruxsat berilmadi. Manzil satridagi qulf belgisini bosib kameraga «Ruxsat» bering, so‘ng «Qayta urinish»ni bosing.",
  PermissionDeniedError:
    "Kameraga ruxsat berilmadi. Manzil satridagi qulf belgisini bosib kameraga «Ruxsat» bering, so‘ng «Qayta urinish»ni bosing.",
  NotFoundError: 'Bu qurilmada kamera topilmadi. Kamerasi bor telefon yoki kompyuterdan oching.',
  DevicesNotFoundError: 'Bu qurilmada kamera topilmadi. Kamerasi bor telefon yoki kompyuterdan oching.',
  NotReadableError:
    'Kamerani boshqa dastur band qilgan. Skype, Zoom, Telegram yoki kamera ochiq boshqa oynani yoping va qayta urinib ko‘ring.',
  TrackStartError:
    'Kamerani boshqa dastur band qilgan. Skype, Zoom, Telegram yoki kamera ochiq boshqa oynani yoping va qayta urinib ko‘ring.',
  OverconstrainedError: 'Kamera talab qilingan sifatni qo‘llab-quvvatlamadi. Boshqa kamera bilan urinib ko‘ring.',
  SecurityError: 'Brauzer sozlamalari bu sahifada kameraga ruxsat bermayapti.',
  AbortError: 'Kamera kutilmaganda uzildi. Qayta urinib ko‘ring.',
  default: 'Kamerani ochib bo‘lmadi. Qayta urinib ko‘ring.',
};

/** Bosqich tasdiqlanishi uchun ketma-ket necha marta mos kelishi kerak.
 *  Bir lahzalik tasodifiy burilish hisobga olinmasligi uchun. */
const STABLE_HITS = 3;

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
  // Ochilgan blob-havolalar. Effekt ichidagi tozalash `captured` state'ini
  // ko'ra olmaydi (u birinchi renderdagi bo'sh massivni yodda tutadi),
  // shuning uchun ro'yxat ref'da ham saqlanadi.
  const urlsRef = useRef<string[]>([]);

  const [ready, setReady] = useState(false);
  /** Kamerani qayta ochish uchun hisoblagich — sahifani yangilamasdan
   *  (yangilash kiritilgan JSHSHIR va kodni yo'q qilib yuborardi). */
  const [attempt, setAttempt] = useState(0);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [hint, setHint] = useState('Kamera ishga tushmoqda...');
  const [matching, setMatching] = useState(false);
  const [stableHits, setStableHits] = useState(0);
  const [captured, setCaptured] = useState<string[]>([]);

  const step = LIVENESS_STEPS[stepIndex];
  const finished = stepIndex >= LIVENESS_STEPS.length;

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    // srcObject bo'shatilmasa Chrome kamera chirog'ini yonib turgan
    // holatda qoldiradi, hatto treklar to'xtatilgan bo'lsa ham.
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  // ─────────────────────────── Kamerani ochish
  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setCameraError(null);
    setHint('Kamera ishga tushmoqda...');

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        // Eng ko'p uchraydigan sabab brauzer emas, manzil: getUserMedia
        // faqat https:// (yoki localhost) da mavjud. "Boshqa brauzerda
        // oching" deyish odamni bekorga sarson qilardi.
        setCameraError(
          window.isSecureContext
            ? "Bu brauzer kameraga kirishni qo‘llab-quvvatlamaydi. Boshqa brauzerda oching."
            : "Sahifa xavfsiz ulanishda (https) emas — brauzer kameraga ruxsat bermaydi. Havolani https:// bilan oching.",
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
        // Telefon qulflansa, boshqa ilova kamerani olsa yoki USB kamera
        // uzilsa brauzer har doim ham getUserMedia xatosini bermaydi.
        // Bunday holatda "kutilmoqda" deb turish o'rniga aniq qayta
        // ulanish yo'lini beramiz.
        stream.getVideoTracks().forEach((track) => {
          track.onended = () => {
            if (!cancelled && !doneRef.current) {
              setReady(false);
              setCameraError('Kamera uzildi. Qayta ulab, yana urinib ko‘ring.');
            }
          };
        });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {
            /* avtomatik ijro bloklangan bo‘lsa foydalanuvchi bosadi */
          });
        }
        setReady(true);
        setHint('Yuzingiz doira ichida to‘liq ko‘rinsin');
      } catch (err) {
        if (cancelled) return;
        // Har bir DOMException nomi butunlay boshqa sabab va boshqa
        // yechim: ruxsat rad etilgani bilan kamerani boshqa dastur band
        // qilgani bir xil xabar olsa, odam nima qilishni bilmaydi.
        const name = err instanceof DOMException ? err.name : '';
        setCameraError(CAMERA_ERRORS[name] ?? CAMERA_ERRORS.default);
      }
    }

    start();
    return () => {
      cancelled = true;
      stopStream();
    };
  }, [attempt, stopStream]);

  // Uchala kadr olingach kamerani darhol o'chiramiz. Aks holda kadrlar
  // serverga yuklanayotganda (va xato bo'lsa — undan ham uzoqroq)
  // kamera chirog'i yonib turaverardi: odam suratga olish tugaganini
  // ko'rib turibdi, kamera esa hali ham unga qarab turibdi.
  useEffect(() => {
    if (finished) stopStream();
  }, [finished, stopStream]);

  // ─────────────────────────── Kadr olish

  /** Bitta video kadridan ikki nusxa: yo'naltirish uchun kichik va saqlash
   *  uchun to'liq. Saqlanadigan kadr AYNAN tekshirilgan kadr bo'lishi kerak —
   *  ilgari to'liq kadr bir lahza keyin olinardi, odam boshini qaytara
   *  boshlagan bo'lardi va server "talabga mos kelmadi" deb rad etardi. */
  const grabPair = useCallback(async (): Promise<{ probe: Blob; full: Blob } | null> => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return null;
    const draw = (maxWidth: number) => {
      const scale = Math.min(1, maxWidth / video.videoWidth);
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas;
    };
    const full = draw(MAX_FRAME_WIDTH);
    const small = document.createElement('canvas');
    const scale = Math.min(1, PROBE_WIDTH / full.width);
    small.width = Math.round(full.width * scale);
    small.height = Math.round(full.height * scale);
    small.getContext('2d')?.drawImage(full, 0, 0, small.width, small.height);
    const toBlob = (c: HTMLCanvasElement, q: number) =>
      new Promise<Blob | null>((resolve) => c.toBlob((b) => resolve(b), 'image/jpeg', q));
    const [probe, fullBlob] = await Promise.all([toBlob(small, 0.65), toBlob(full, FRAME_QUALITY)]);
    return probe && fullBlob ? { probe, full: fullBlob } : null;
  }, []);

  // ─────────────────────────── Jonli yo‘naltirish
  useEffect(() => {
    if (!ready || finished || cameraError || submitting) return;

    let stopped = false;
    const timer = window.setInterval(async () => {
      if (stopped || busyRef.current || doneRef.current) return;
      busyRef.current = true;
      try {
        const pair = await grabPair();
        if (!pair || stopped) return;
        const probe = pair.probe;

        const result = await checkPose(step, probe);
        if (stopped) return;

        setHint(result.hint);
        setMatching(result.ok);

        if (!result.ok) {
          hitsRef.current = 0;
          setStableHits(0);
          return;
        }

        hitsRef.current += 1;
        setStableHits(hitsRef.current);
        if (hitsRef.current < STABLE_HITS) return;

        // Bosqich tasdiqlandi — saqlanadi AYNAN shu tekshirilgan kadrning to'liq nusxasi.
        const full = pair.full;
        if (stopped) return;
        hitsRef.current = 0;
        setStableHits(0);
        framesRef.current = [...framesRef.current, full];
        const url = URL.createObjectURL(full);
        urlsRef.current = [...urlsRef.current, url];
        setCaptured((prev) => [...prev, url]);
        setMatching(false);
        setStepIndex((i) => i + 1);
      } catch (err) {
        // Tarmoq uzilishi — keyingi urinishda davom etadi. Bitta so'rov
        // o'tmasligi normal; lekin server "juda ko'p so'rov" (429) desa —
        // bir tarmoqdan (institut Wi‑Fi) ko'p odam birdaniga topshirmoqda:
        // odam qotib qoldi deb o'ylamasin, aytamiz.
        if (err instanceof ApiError && err.status === 429) {
          setHint('Server band — hozir ko‘p odam ro‘yxatdan o‘tmoqda. Bir necha soniya kuting, jarayon o‘zi davom etadi.');
        }
      } finally {
        busyRef.current = false;
      }
    }, PROBE_INTERVAL_MS);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [ready, finished, cameraError, submitting, step, grabPair]);

  // ─────────────────────────── Uch kadr yig‘ilgach yuborish
  useEffect(() => {
    if (!finished || doneRef.current || submitting) return;
    doneRef.current = true;
    onSubmit(framesRef.current);
  }, [finished, submitting, onSubmit]);

  // Serverdan xato kelsa boshidan boshlaymiz — qaysi kadr o‘tmaganini
  // bilmaymiz, va yarim to‘plam bilan davom etish noto‘g‘ri natija
  // beradi.
  const reset = useCallback(() => {
    doneRef.current = false;
    hitsRef.current = 0;
    setStableHits(0);
    framesRef.current = [];
    urlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    urlsRef.current = [];
    setCaptured([]);
    setStepIndex(0);
    setMatching(false);
    // Eski maslahat matni ("Boshingizni chapga buring") qolib ketmasin:
    // bosqich 1 ga qaytdi, lekin yozuv oldingi urinishdan qolgan bo'lardi.
    setHint('');
    // Kadrlar to'plangach kamera o'chirilgan — boshidan boshlash uchun
    // uni qaytadan ochish kerak.
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!externalError) return;
    reset();
  }, [externalError, reset]);

  // Sahifadan chiqilganda ochiq blob-havolalarni bo'shatamiz. Ref orqali:
  // state'ni o'qiydigan bo'sh bog'liqlikli effekt birinchi renderdagi
  // bo'sh massivni ko'radi va hech narsani bo'shatmasdi (xotira oqimi).
  useEffect(
    () => () => {
      urlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlsRef.current = [];
    },
    [],
  );

  // ─────────────────────────── Ko‘rinish
  if (cameraError) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 border-b border-border pb-2">
          <MicroLabel>Bosqich 4 — Yuz</MicroLabel>
          <span className="ms-auto">
            <StatusLamp status="alert" label="Kamera ochilmadi" />
          </span>
        </div>
        <Notice tone="danger" icon={VideoOff} title="Kamera ochilmadi">
          {cameraError}
        </Notice>
        {/* Sahifani YANGILAMAYMIZ: yangilash kiritilgan JSHSHIR, guruh
            kodi va berilgan rozilikni yo'q qilib, odamni birinchi
            bosqichga qaytarib yuborardi. Faqat kamera qayta ochiladi. */}
        <Button size="lg" icon={RotateCcw} onClick={() => setAttempt((n) => n + 1)} fullWidth>
          Qayta urinish
        </Button>
      </div>
    );
  }

  const total = LIVENESS_STEPS.length;
  const ui = finished ? null : STEP_UI[step];

  /** Kamera holati — RANG emas, SO'Z bilan aytiladi. */
  const camera: { status: IntelStatus; label: string } = submitting
    ? { status: 'warn', label: 'Yuborilmoqda' }
    : finished
      ? { status: 'ok', label: 'Bajarildi' }
      : !ready
        ? { status: 'warn', label: 'Ishga tushmoqda' }
        : matching
          ? { status: 'ok', label: 'Mos keldi' }
          : { status: 'idle', label: 'Kutilmoqda' };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <MicroLabel>Bosqich 4 — Yuz</MicroLabel>
          <h2 className="mt-0.5 text-[15px] font-semibold text-fg">Yuzingizni kamera orqali tasdiqlang</h2>
        </div>
        <span className="shrink-0 pt-0.5">
          <StatusLamp status={camera.status} label={camera.label} pulse={camera.status === 'warn'} />
        </span>
      </div>
      <p className="-mt-2 text-[13px] leading-relaxed text-muted">
          Uch bosqich: to&apos;g&apos;riga qarang, so&apos;ng boshingizni chapga va o&apos;ngga
          buring. Yorug&apos; joyda turing, ko&apos;zoynak va niqobni oling.
      </p>

      {/* Kadr hisobi — rangsiz ham o'qiladigan o'lchov. */}
      <div className="flex items-center gap-2 border-y border-border py-1.5">
        <MicroLabel>Olingan kadr</MicroLabel>
        <CodeText className="text-[13px] font-semibold text-fg">
          {captured.length}/{total}
        </CodeText>
        <span className="ms-auto">
          <MicroLabel>{finished ? 'Tayyor' : matching ? `Barqaror ${stableHits}/${STABLE_HITS}` : 'Yo‘naltirilmoqda'}</MicroLabel>
        </span>
      </div>

      {/* Doira ichidagi jonli tasvir */}
      <div className="relative mx-auto aspect-square w-full max-w-[300px]">
        <ProgressRing done={captured.length} total={total} active={matching} />

        <div
          className={cn(
            'absolute inset-[9%] overflow-hidden rounded-full border-[3px] bg-surface-2 transition-colors duration-200',
            matching || finished ? 'border-success' : 'border-border-strong',
          )}
        >
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            aria-label="Kameradan jonli tasvir"
            className="h-full w-full scale-x-[-1] object-cover"
          />
          {!ready && !finished && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-black/60 text-white">
              <ScanFace size={30} className="animate-pulse" aria-hidden="true" />
              {/* Faqat pulsatsiya qilayotgan ikonka "sindimi yoki
                  yuklanyaptimi" degan savol tug'dirardi. */}
              <span className="text-xs">Kamera ishga tushmoqda...</span>
            </div>
          )}
        </div>

        {/* Burilish yo'nalishi ko'rsatkichi */}
        {ui?.arrow && !matching && (
          <span
            className={cn(
              'pointer-events-none absolute top-1/2 -translate-y-1/2 animate-pulse text-4xl font-bold text-primary',
              step === 'left' ? 'left-0' : 'right-0',
            )}
            aria-hidden
          >
            {ui.arrow}
          </span>
        )}
      </div>

      {/* Bosqich va maslahat.
          aria-live butun blokda: ko'rmaydigan foydalanuvchi uchun aynan
          shu ikki qator yagona yo'riqnoma — bosqich o'zgargani ham,
          "yuz topilmadi" kabi maslahat ham eshitilishi kerak. Ilgari
          faqat sarlavhada edi va jonli maslahat umuman aytilmasdi. */}
      <div className="text-center" role="status" aria-live="polite" aria-atomic="true">
        {finished ? (
          <p className="flex items-center justify-center gap-1.5 text-sm font-semibold text-success">
            <Check size={16} aria-hidden="true" />
            Uchala bosqich bajarildi
          </p>
        ) : (
          <>
            <p className="text-[15px] font-semibold text-fg">
              <CodeText>
                {stepIndex + 1}/{total}
              </CodeText>{' '}
              — {ui?.title}
            </p>
            <p
              className={cn('mt-1 text-[13px] font-medium transition-colors', matching ? 'text-success' : 'text-muted')}
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
              className={cn(
                'h-14 w-14 overflow-hidden rounded-control border-2',
                captured[i] ? 'border-success' : 'border-dashed border-border-strong',
              )}
            >
              {captured[i] ? (
                <img src={captured[i]} alt="" className="h-full w-full scale-x-[-1] object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-subtle">
                  <CodeText className="text-[12px]">{i + 1}</CodeText>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {externalError && (
        // role="alert" o'ramda: Notice faqat "danger" ohangida e'lon
        // qiladi, bu xabar esa tiklanadigan (warning), lekin baribir
        // eshitilishi shart — aks holda ko'rmaydigan foydalanuvchi
        // nega hammasi boshidan boshlanganini bilmaydi.
        <div role="alert">
          <Notice tone="warning">{externalError} Bosqichlar boshidan boshlandi.</Notice>
        </div>
      )}

      {submitting && (
        <p className="flex items-center justify-center gap-1.5 text-center text-[13px] font-medium text-primary" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          Yuz saqlanmoqda...
        </p>
      )}

      {captured.length > 0 && !submitting && (
        <Button variant="ghost" size="sm" icon={RotateCcw} onClick={reset} className="mx-auto">
          Boshidan boshlash
        </Button>
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
            className={isDone ? 'stroke-success' : isActive ? 'animate-pulse stroke-primary' : 'stroke-border-strong'}
          />
        );
      })}
    </svg>
  );
}
