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
  /** Video konteynerga qanday joylashtiriladi.
   *
   * 'cover' (standart) — konteynerni to'ldiradi va ortiqchasini QIRQADI.
   * Miniatyuralar uchun to'g'ri: ular kichik va bir xil o'lchamli
   * kataklar, bo'sh qora chekkalar u yerda faqat xunuk ko'rinadi.
   *
   * 'contain' — butun kadrni ko'rsatadi, kerak bo'lsa qora chekka
   * qoldiradi. Asosiy ko'rinish uchun aynan shu kerak: u qolgan bo'sh
   * joyni egallaydi, ya'ni nisbati 16:9 bo'lmaydi, va 'cover' bilan
   * kadrning yuqori/quyi yoki chap/o'ng qismi ko'rinmay qolardi — aynan
   * operator kuzatishi kerak bo'lgan joy. */
  fit?: 'cover' | 'contain';
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
  /** Standart holatda src/lib/streamLoadQueue.ts (admin panjarasi uchun,
   * MAX 8) ishlatiladi — boshqa alohida navbat kerak bo'lsa (masalan
   * src/lib/monitorThumbnailQueue.ts, kichikroq MAX bilan) shu yerdan
   * almashtiriladi. priority=true bo'lsa ikkalasi ham chaqirilmaydi. */
  acquireSlot?: (id: string, onRevoked: () => void) => Promise<void>;
  releaseSlot?: (id: string) => void;
}

const LOAD_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 6;
// Yuklab bo'lmasa, doimiy "xato" holatiga tushib qolish o'rniga fon
// rejimida qayta urinib turadi (backoff ortib boruvchi, 20s'da to'xtaydi)
// — camera.status='live' bo'lgan kamera uchun bu deyarli har doim
// navbat/server bandligi kabi vaqtinchalik holat, haqiqatan o'lik oqim
// emas (aks holda backend uni "live" deb belgilamas edi). Faqat juda
// ko'p urinishdan keyin (bir necha daqiqa) haqiqatan muammo borligini
// ko'rsatamiz.
const RETRY_BASE_MS = 6_000;
const RETRY_MAX_MS = 20_000;
const SHOW_ERROR_AFTER_ATTEMPTS = 10;

// Jonli chekkadan orqada qolishni kuzatish.
//
// Nega kerak: bu monitoring devori — ekrandagi tasvir HOZIRGI holatni
// ko'rsatishi shart. HLS pleyeri esa tabiatan orqada qoladi va bu
// kechikish TO'PLANADI: brauzer fon yorlig'idagi videoni sekinlashtiradi
// yoki to'xtatadi, tarmoq uzilib-ulanadi, video element esa qayerda
// to'xtagan bo'lsa o'sha yerdan davom etadi — jonli chekkaga o'zi
// qaytmaydi. Bir necha soat ochiq turgan devor shu tarzda daqiqalab
// orqada qolishi mumkin.
//
// Shuning uchun: agar bufferlangan chekka bilan joriy vaqt orasidagi
// farq MAX dan oshsa, jonli chekkaga sakraymiz. Sakrash ko'rinadi
// (tasvir bir zumda "ilgarilaydi"), lekin eskirgan tasvirni ko'rsatib
// turishdan yaxshiroq.
const LIVE_EDGE_CHECK_MS = 3_000;
// Bu chegaralar segmentlar 20 soniyalik bo'lgan davrdan qolgan edi (12s
// — bir segmentdan kichik, ya'ni hech qachon ishga tushmasdi). Endi
// segmentlar 1 soniya, LL-HLS qismlari esa 250ms, shuning uchun 3
// soniyadan ortiq orqada qolish allaqachon anomaliya.
const MAX_BEHIND_LIVE_S = 3;
const TARGET_BEHIND_LIVE_S = 1;

export default function LiveVideoPlayer({
  streamUrl,
  className = '',
  fit = 'cover',
  startDelayMs = 0,
  priority = false,
  cameraId,
  showDetections = false,
  zoneEditing = false,
  zonePoints = [],
  onZonePointAdd,
  acquireSlot = acquireStreamSlot,
  releaseSlot = releaseStreamSlot,
}: LiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [loading, setLoading] = useState(true);
  const hlsRetriesRef = useRef(0); // HLS.js's own in-attempt network/media recovery count
  const attemptRef = useRef(0); // how many whole attach cycles have been tried, for backoff + the error threshold
  const detection = useLiveDetection(cameraId, showDetections && !error);

  useEffect(() => {
    setError(false);
    setRetrying(false);
    setLoading(true);
    hlsRetriesRef.current = 0;
    attemptRef.current = 0;
    const video = videoRef.current;
    if (!video || !streamUrl) return;

    let cancelled = false;
    let hlsInstance: Hls | null = null;
    let loadTimer: ReturnType<typeof setTimeout> | null = null;
    let startTimer: ReturnType<typeof setTimeout> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let liveEdgeTimer: ReturnType<typeof setInterval> | null = null;
    let onVisible: (() => void) | null = null;

    function clearAllTimers() {
      if (loadTimer) clearTimeout(loadTimer);
      if (startTimer) clearTimeout(startTimer);
      if (retryTimer) clearTimeout(retryTimer);
      loadTimer = startTimer = retryTimer = null;
    }

    function teardownPlayback() {
      hlsInstance?.destroy();
      hlsInstance = null;
      video!.removeAttribute('src');
      video!.load();
    }

    // Always called on cleanup, whether or not a slot was ever actually
    // held: a card can unmount (e.g. the user paginates to the next 8
    // thumbnails) WHILE STILL WAITING for a turn, before acquireSlot's
    // promise even resolves. Gating this on "did we ever get granted a
    // slot" left such waiters as ghost entries sitting in the queue
    // forever (or until eventually granted, then immediately
    // self-revoked — wasted churn), which could let a page-1 leftover
    // jump the line ahead of a genuinely-waiting page-2 thumbnail.
    // releaseSlot() itself already checks both the active-holder and
    // waiter lists and is a safe no-op if this id is in neither, so
    // calling it unconditionally here is always correct.
    function releaseQueueSlot() {
      releaseSlot(streamUrl!);
    }

    function markReady() {
      if (!cancelled) {
        setLoading(false);
        setError(false);
        setRetrying(false);
        attemptRef.current = 0;
      }
    }

    // Bir marta ishlab, doim "xato" holatiga qotib qolish o'rniga — fon
    // rejimida qayta urinib turadi. camera.status='live' bo'lgani uchun
    // bu deyarli har doim vaqtinchalik navbat/server bandligi, haqiqiy
    // o'lik oqim emas (§ RETRY_BASE_MS izohiga qarang).
    function scheduleRetry() {
      if (cancelled) return;
      if (loadTimer) {
        clearTimeout(loadTimer);
        loadTimer = null;
      }
      teardownPlayback();
      releaseQueueSlot();
      attemptRef.current += 1;
      setLoading(true);
      setRetrying(true);
      setError(attemptRef.current >= SHOW_ERROR_AFTER_ATTEMPTS);
      const backoff = Math.min(RETRY_BASE_MS + attemptRef.current * 2000, RETRY_MAX_MS);
      retryTimer = setTimeout(() => {
        if (!cancelled) void start();
      }, backoff);
    }

    function markFailed() {
      scheduleRetry();
    }

    async function attach() {
      if (!video) return;
      hlsRetriesRef.current = 0;
      const isHls = streamUrl!.endsWith('.m3u8');

      loadTimer = setTimeout(() => {
        if (cancelled) return;
        if (video.videoWidth === 0) markFailed();
      }, LOAD_TIMEOUT_MS);

      // HLS uchun HAR DOIM avval hls.js sinaladi; brauzerning o'z HLS
      // qo'llab-quvvatlashiga faqat hls.js ishlamaydigan joyda
      // (Safari/iOS — u yerda MSE cheklangan, native HLS esa haqiqatan
      // yaxshi ishlaydi) tushamiz.
      //
      // Avval bu shart `!video.canPlayType('application/vnd.apple.mpegurl')`
      // edi va aynan shu Chrome'da pleyerni o'ldirgan: Chromium bu
      // MIME uchun "maybe" qaytaradi (bo'sh satr emas!), ya'ni shart
      // false bo'lib, hls.js chetlab o'tilardi va `.m3u8` to'g'ridan-
      // to'g'ri <video src> ga berilardi — Chromium'da esa native HLS
      // umuman yo'q. Production'da o'lchangan (Chrome 148): 9 tadan 9
      // ta pleyer `readyState: 1`, `paused: true`, `currentTime: 0`
      // holatida qotib qolgan. canPlayType'ning "maybe" javobi hech
      // narsani kafolatlamaydi, shuning uchun unga qaror qabul
      // qilishda tayanib bo'lmaydi.
      const { default: HlsLib } = isHls
        ? await import('hls.js')
        : { default: null as unknown as typeof import('hls.js').default };
      if (cancelled) return;

      if (isHls && HlsLib.isSupported()) {

        hlsInstance = new HlsLib({
          enableWorker: true,
          lowLatencyMode: true,
          // liveSyncDurationCount ATAYLAB berilmagan. hls.js pleylistdagi
          // PART-HOLD-BACK qiymatini (production'da o'lchangan: 0.625s)
          // faqat bu sozlama BERILMAGAN bo'lsa ishlatadi — qo'lda qiymat
          // qo'yilsa, LL-HLS sinxronizatsiyasi butunlay chetlab o'tiladi.
          // Avval bu yerda 3 turardi va aynan shu sababli server 0.6
          // soniyalik kechikish taklif qilib turganda pleyer jonli
          // chekkadan 11 soniya orqada qotib qolgan edi.
          maxLiveSyncPlaybackRate: 1.5,
          backBufferLength: 0,
          // Oldinga buferni kichik ushlaymiz: katta bufer sekin tarmoqda
          // uzilishlardan himoya qiladi, lekin monitoring devorida
          // buferning har soniyasi — real vaqtdan orqada qolgan soniya.
          maxBufferLength: 4,
          maxMaxBufferLength: 8,
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
          if (retryableNetwork && hlsRetriesRef.current < MAX_RETRIES) {
            hlsRetriesRef.current += 1;
            hlsInstance?.startLoad(-1);
            return;
          }
          if (data.type === HlsLib.ErrorTypes.MEDIA_ERROR && hlsRetriesRef.current < MAX_RETRIES) {
            hlsRetriesRef.current += 1;
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

    async function start() {
      if (cancelled) return;
      if (!priority) {
        // onRevoked: navbat (streamLoadQueue) adolatli aylanish uchun
        // joyni boshqa ko'rinadigan kartaga bergan — bu XATO EMAS, faqat
        // "hozircha to'xtat" signali, shuning uchun xato holatini
        // ko'rsatmasdan, jim ravishda qayta navbatga turamiz.
        await acquireSlot(streamUrl!, () => {
          if (cancelled) return;
          if (loadTimer) {
            clearTimeout(loadTimer);
            loadTimer = null;
          }
          teardownPlayback();
          setLoading(true);
          void start();
        });
        if (cancelled) {
          releaseSlot(streamUrl!);
          return;
        }
      }
      await attach();
    }

    // Jonli chekka kuzatuvchisi — yuqoridagi MAX_BEHIND_LIVE_S izohiga
    // qarang. Buferlangan chekkadan hisoblaymiz, shuning uchun HLS ham,
    // oddiy MP4/WebM manba ham bir xil ishlaydi.
    function jumpToLiveEdge(force: boolean) {
      if (cancelled || !video || video.readyState < 2) return;
      const buffered = video.buffered;
      if (!buffered.length) return;
      const edge = buffered.end(buffered.length - 1);
      const behind = edge - video.currentTime;
      if (!force && behind <= MAX_BEHIND_LIVE_S) return;
      if (behind <= TARGET_BEHIND_LIVE_S) return;
      video.currentTime = Math.max(0, edge - TARGET_BEHIND_LIVE_S);
    }

    liveEdgeTimer = setInterval(() => jumpToLiveEdge(false), LIVE_EDGE_CHECK_MS);

    // Brauzer fondagi yorliqda videoni to'xtatadi/sekinlashtiradi, qaytib
    // kelganda esa u o'sha eski nuqtadan davom etadi — devor ochiq turib
    // daqiqalab orqada qolishining eng keng tarqalgan sababi shu.
    onVisible = () => {
      if (document.visibilityState === 'visible') jumpToLiveEdge(true);
    };
    document.addEventListener('visibilitychange', onVisible);

    startTimer = setTimeout(() => {
      if (!cancelled) void start();
    }, startDelayMs);

    return () => {
      cancelled = true;
      clearAllTimers();
      if (liveEdgeTimer) clearInterval(liveEdgeTimer);
      if (onVisible) document.removeEventListener('visibilitychange', onVisible);
      teardownPlayback();
      releaseQueueSlot();
    };
  }, [streamUrl, startDelayMs, priority, acquireSlot, releaseSlot]);

  if (!streamUrl) return null;

  if (error) {
    return (
      <div className={`absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-white/60 ${className}`}>
        <VideoOff size={20} />
        <span className="text-[11px] font-medium">Video oqimini yuklab bo&apos;lmadi</span>
        <span className="text-[10px] text-white/40">Qayta urinilmoqda...</span>
      </div>
    );
  }

  return (
    <>
      {loading && (
        <div className="absolute inset-0 z-[1] flex flex-col items-center justify-center gap-1.5 bg-slate-900/80">
          <Loader2 size={22} className="animate-spin text-slate-400" />
          {retrying && <span className="text-[10px] font-medium text-slate-400">Navbatda...</span>}
        </div>
      )}
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={`absolute inset-0 h-full w-full ${fit === 'contain' ? 'object-contain' : 'object-cover'} ${className}`}
      />
      {showDetections && <FaceDetectionOverlay videoRef={videoRef} detection={detection.result} fit={fit} />}
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
