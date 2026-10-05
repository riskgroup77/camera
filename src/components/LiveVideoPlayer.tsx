import { useEffect, useRef, useState } from 'react';
import type Hls from 'hls.js';
import { Loader2, VideoOff } from 'lucide-react';
import FaceDetectionOverlay from './FaceDetectionOverlay';
import { cameraIdFromStreamUrl, noteWebrtcResult, startWebrtc, webrtcAllowed, type WebrtcSession } from '../lib/webrtcStream';
import { serverNow } from '../lib/serverClock';
import type { LiveDetectionResult } from '../types';
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
  /** Har yangi yuz tahlili natijasi — ota komponent hisoblagich ko'rsatishi uchun. */
  onDetection?: (result: LiveDetectionResult | null) => void;
  /** Berilsa, video ustiga bosish orqali taqiqlangan zona ko'pburchagini
   * chizish rejimi yoqiladi (CameraZoneModal.tsx) — koordinatalar
   * app/models/camera.py's restricted_zone_polygon bilan bir xil formatda
   * (0-1 normallashtirilgan) qaytariladi. */
  zoneEditing?: boolean;
  zonePoints?: [number, number][];
  onZonePointAdd?: (point: [number, number]) => void;
  /** Standart holatda src/lib/streamLoadQueue.ts (admin panjarasi uchun,
   * MAX 8) ishlatiladi — boshqa alohida navbat kerak bo'lsa (masalan
   * eski miniatyura navbati, endi rasm keshi bilan almashtirilgan) shu yerdan
   * almashtiriladi. priority=true bo'lsa ikkalasi ham chaqirilmaydi. */
  acquireSlot?: (id: string, onRevoked: () => void) => Promise<void>;
  releaseSlot?: (id: string) => void;
  /** Oqim manzilining O'ZI yaroqsiz bo'lganda chaqiriladi (403 — imzo
   * muddati tugagan yoki imzosiz havola, 404 — MediaMTX'da yo'l yo'q).
   * Bunday holatda AYNAN SHU manzilni qayta so'rash hech qachon yordam
   * bermaydi: egasi kameralar ro'yxatini yangilab, yangi imzolangan
   * havola olishi kerak (useWallCameras.refreshStreams). Chaqiruv
   * cheklangan: pleyer buni faqat fatal xatoda, backoff bilan qiladi. */
  onStreamUnavailable?: () => void;
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

/** Qayta urinish kutish vaqti — TASODIFIY qo'shimcha bilan.
 *
 * Nega tasodif kerak: MediaMTX shardi qayta ishga tushganda (yoki tarmoq
 * bir zumga uzilganda) devordagi 16 ta katakning HAMMASI bir vaqtda xato
 * oladi. Qat'iy backoff bilan ular keyin ham bir vaqtda uriniladi: +8s
 * da o'n oltitasi birdan, +10s da yana o'n oltitasi... Situatsion markaz
 * televizori bitta emas, va har biri shu zarbani takrorlaydi — server
 * ko'tarilishi bilan ulanishlar "bo'roni" keladi va shard qayta
 * bo'g'iladi. Shu sababli urinishlar ±20% ga yoyiladi.
 *
 * Xuddi shu muammo WebSocket ulanishida allaqachon shunday hal qilingan
 * (src/lib/realtime.ts — reconnectDelay), HLS pleyerida esa qolib
 * ketgan edi. */
export function streamRetryDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(RETRY_BASE_MS + attempt * 2000, RETRY_MAX_MS);
  return Math.round(base * (0.8 + random() * 0.4));
}

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
// Qotib qolish nazorati: video "o'ynayapti" deb turib, shuncha vaqt ichida
// currentTime bir millisekund ham siljimasa — oqim qotgan (kamera qayta
// ulangan, MediaMTX yo'lni yangilagan, tarmoq uzilgan). Bunday holatda
// hls.js ko'pincha o'zini sog' deb biladi va xato bermaydi, tasvir esa
// operator ekranida qotib turaveradi. To'liq qayta ulanamiz.
const FROZEN_AFTER_MS = 8_000;

export default function LiveVideoPlayer({
  streamUrl,
  className = '',
  fit = 'cover',
  startDelayMs = 0,
  priority = false,
  cameraId,
  showDetections = false,
  onDetection,
  zoneEditing = false,
  zonePoints = [],
  onZonePointAdd,
  acquireSlot = acquireStreamSlot,
  releaseSlot = releaseStreamSlot,
  onStreamUnavailable,
}: LiveVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // Hozir ko'rinayotgan kadrning server soatidagi payti (ms) — HLS
  // EXT-X-PROGRAM-DATE-TIME. Yuz ramkalari aynan shu kadrga qo'yiladi
  // (lib/liveTracks.ts); null — pleylistda vaqt belgisi yo'q.
  const videoClockRef = useRef<() => number | null>(() => null);
  const [error, setError] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [loading, setLoading] = useState(true);
  /** Manzilning o'zi rad etilgan (403) — imzo muddati tugagan. Bu boshqa
   * xatolardan farq qiladi: "qayta urinilmoqda" emas, "havola yangilanmoqda". */
  const [expired, setExpired] = useState(false);
  // Effekt bog'liqligiga tushmasligi uchun ref orqali: chaqiruvchi har
  // renderda yangi funksiya bersa ham oqim uzilib qayta ulanmaydi.
  const unavailableRef = useRef(onStreamUnavailable);
  unavailableRef.current = onStreamUnavailable;
  const hlsRetriesRef = useRef(0); // HLS.js's own in-attempt network/media recovery count
  const attemptRef = useRef(0); // how many whole attach cycles have been tried, for backoff + the error threshold
  // Video qaysi yo'l bilan ulangan — skaner so'roviga qo'shiladi.
  const playerModeRef = useRef<'webrtc' | 'hls' | null>(null);
  const detection = useLiveDetection(cameraId, showDetections && !error, () => playerModeRef.current);
  const onDetectionRef = useRef(onDetection);
  onDetectionRef.current = onDetection;
  useEffect(() => {
    onDetectionRef.current?.(detection.result);
  }, [detection.result]);
  // `startDelayMs` — faqat BIRINCHI ulanishni siljitish uchun (panjarada
  // hamma pleyer bir vaqtda ulanmasin). Uni effekt bog'liqligiga qo'yish
  // mumkin emas: panjaradagi bitta kamera oflayn bo'lishi yoki bitta
  // katak kattalashtirilishi qolgan kataklarning kechikishini
  // surib yuboradi va O'SHA PAYTDA ishlab turgan oqimlar uzilib, qaytadan
  // ulanardi (ekran qorayib olardi). Ref orqali — qiymat o'zgarsa ham
  // effekt qayta ishga tushmaydi.
  const startDelayRef = useRef(startDelayMs);
  startDelayRef.current = startDelayMs;

  useEffect(() => {
    setError(false);
    setRetrying(false);
    setExpired(false);
    setLoading(true);
    hlsRetriesRef.current = 0;
    attemptRef.current = 0;
    const video = videoRef.current;
    if (!video || !streamUrl) return;

    let cancelled = false;
    let hlsInstance: Hls | null = null;
    let webrtc: WebrtcSession | null = null;
    let webrtcAbort: AbortController | null = null;
    videoClockRef.current = () => {
      // WebRTC: tasvir deyarli real vaqtda — server soati (brauzer soatiga
      // nisbatan farqi skaner javobidan olinadi, lib/serverClock.ts).
      if (webrtc) return serverNow();
      const playing = hlsInstance?.playingDate?.getTime();
      if (playing && Number.isFinite(playing)) return playing;
      // Safari/iOS'ning o'z HLS pleyeri: pleylist boshining payti + joriy o'rin.
      const start = (video as (HTMLVideoElement & { getStartDate?: () => Date }) | null)?.getStartDate?.()?.getTime();
      return start && Number.isFinite(start) && video ? start + video.currentTime * 1000 : null;
    };
    let loadTimer: ReturnType<typeof setTimeout> | null = null;
    let startTimer: ReturnType<typeof setTimeout> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let liveEdgeTimer: ReturnType<typeof setInterval> | null = null;
    let onVisible: (() => void) | null = null;
    // `attach()` qo'ygan <video> hodisa tinglovchilarini olib tashlaydi.
    // Har qayta urinish (scheduleRetry -> start -> attach) yangi
    // tinglovchi qo'yadi; `{ once: true }` esa ULAR ISHGA TUSHSAGINA
    // o'zini o'chiradi. Oqim ishga tushmayotgan kamerada (aynan qayta
    // urinish aylanmasiga tushadigan holat) ular hech qachon ishlamaydi
    // va bir necha soat davomida bitta <video> elementida yuzlab
    // tinglovchi (har biri eski effekt yopilmasini ushlab turadi)
    // to'planib qolardi; eskisi keyinroq ishga tushib, hali ulanmagan
    // pleyerni "tayyor" deb belgilab ham qo'yardi.
    let detachMediaListeners: (() => void) | null = null;

    function clearAllTimers() {
      if (loadTimer) clearTimeout(loadTimer);
      if (startTimer) clearTimeout(startTimer);
      if (retryTimer) clearTimeout(retryTimer);
      loadTimer = startTimer = retryTimer = null;
    }

    function teardownPlayback() {
      detachMediaListeners?.();
      detachMediaListeners = null;
      webrtcAbort?.abort();
      webrtcAbort = null;
      webrtc?.close();
      webrtc = null;
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
        setExpired(false);
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
      const backoff = streamRetryDelay(attemptRef.current);
      retryTimer = setTimeout(() => {
        if (!cancelled) void start();
      }, backoff);
    }

    function markFailed() {
      scheduleRetry();
    }

    /** WebRTC (~0.5 s kechikish) — muvaffaqiyatli bo'lsa true. Aks holda
     *  chaqiruvchi HLS'ga o'tadi (lib/webrtcStream.ts izohiga qarang). */
    async function attachWebrtc(): Promise<boolean> {
      const id = cameraIdFromStreamUrl(streamUrl);
      if (!video || !id || !webrtcAllowed()) return false;
      webrtcAbort = new AbortController();
      try {
        const session = await startWebrtc(id, video, webrtcAbort.signal);
        if (cancelled) {
          session.close();
          return true;
        }
        webrtc = session;
        playerModeRef.current = 'webrtc';
        noteWebrtcResult(true);
        session.onFailure(() => {
          if (!cancelled) scheduleRetry();
        });
        const onPlaying = () => {
          if (video.videoWidth > 0) markReady();
        };
        video.addEventListener('playing', onPlaying);
        video.addEventListener('loadeddata', onPlaying);
        detachMediaListeners = () => {
          video.removeEventListener('playing', onPlaying);
          video.removeEventListener('loadeddata', onPlaying);
        };
        try {
          await video.play();
        } catch {
          // Avtomatik ijro bloklangan bo'lishi mumkin (video muted — odatda o'tadi)
        }
        return true;
      } catch {
        webrtcAbort = null;
        if (cancelled) return true;
        noteWebrtcResult(false);
        return false;
      }
    }

    async function attach() {
      if (!video) return;
      hlsRetriesRef.current = 0;
      loadTimer = setTimeout(() => {
        if (cancelled) return;
        if (video.videoWidth === 0) markFailed();
      }, LOAD_TIMEOUT_MS);
      if (await attachWebrtc()) return;
      if (cancelled) return;
      playerModeRef.current = 'hls';
      const isHls = streamUrl!.endsWith('.m3u8');

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

      const usedHlsJs = isHls && HlsLib.isSupported();
      if (usedHlsJs) {
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
          // HLS endi faqat WebRTC ishlamagan joyda (LAN tashqarisi). MediaMTX
          // fmp4 variantida LL-HLS qismlari yo'q, ya'ni PART-HOLD-BACK ham
          // yo'q va hls.js standart 3 x segment (~6 s) orqada turardi.
          // Bo'laklar 1-2 s — 3 s zaxira pleylistning bitta kechikishiga
          // ham chidaydi, 7 s dan orqada qolsa jonli chekkaga sakraydi.
          liveSyncDuration: 3,
          liveMaxLatencyDuration: 7,
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
          // 403 — nginx imzoni rad etdi (muddati tugagan yoki imzosiz
          // havola). AYNAN SHU manzilni qayta so'rash hech qachon
          // yordam bermaydi, faqat serverni bezovta qiladi: darhol
          // egasidan yangi imzolangan havola so'raymiz va sekin
          // backoff bilan kutamiz (manzil o'zgarsa effekt qaytadan
          // ishga tushadi). Ilgari 403 oddiy fatal xato sifatida
          // qayta-qayta urinilardi va operator "yuklab bo'lmadi"
          // deganidan boshqa hech narsa ko'rmasdi.
          if (data.type === HlsLib.ErrorTypes.NETWORK_ERROR && code === 403) {
            if (!cancelled) setExpired(true);
            unavailableRef.current?.();
            markFailed();
            return;
          }
          const retryableNetwork =
            data.type === HlsLib.ErrorTypes.NETWORK_ERROR &&
            (code === 404 || code === 401 || code === 500 || code === 0);
          if (!data.fatal && !retryableNetwork) return;
          if (retryableNetwork && hlsRetriesRef.current >= MAX_RETRIES && code === 404) {
            // MediaMTX'da yo'l yo'q — ro'yxatdagi manzil eskirgan bo'lishi
            // mumkin, egasidan yangisini so'raymiz.
            unavailableRef.current?.();
          }
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
      }

      const onLoadedData = () => markReady();
      const onPlaying = () => {
        if (video.videoWidth > 0) markReady();
      };
      if (!usedHlsJs) {
        video.src = streamUrl!;
        video.addEventListener('loadeddata', onLoadedData);
      }
      video.addEventListener('playing', onPlaying);
      detachMediaListeners = () => {
        video.removeEventListener('loadeddata', onLoadedData);
        video.removeEventListener('playing', onPlaying);
      };

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

    let lastTime = -1;
    let lastProgressAt = Date.now();
    function checkFrozen() {
      // Nazorat FAQAT haqiqatan tasvir chiqayotgan pleyer uchun ishlaydi
      // (readyState + videoWidth). Hali ulanmagan, navbatda turgan yoki
      // fon yorlig'idagi pleyerda hisoblagich nolga qaytariladi, ya'ni
      // sog'lom oqimda bekorga ishga tushmaydi.
      //
      // Ilgari bu yerda `!hlsInstance` sharti ham bor edi va nazorat
      // hls.js ISHLATILMAGAN yo'llarda — Safari/iOS'ning o'z HLS
      // pleyerida va MP4/WebM manbalarda — umuman ishlamasdi: aynan
      // o'sha brauzerlarda qotib qolgan tasvir hech qachon o'z-o'zidan
      // tuzalmasdi.
      if (
        cancelled ||
        !video ||
        document.visibilityState !== 'visible' ||
        video.readyState < 2 ||
        video.videoWidth === 0
      ) {
        lastProgressAt = Date.now();
        lastTime = -1;
        return;
      }
      if (video.paused) {
        // Brauzer ijroni to'xtatgan (masalan fon yorlig'idan qaytganda) —
        // muted video uchun qayta boshlash ruxsat etilgan.
        void video.play().catch(() => undefined);
      }
      if (video.currentTime !== lastTime) {
        lastTime = video.currentTime;
        lastProgressAt = Date.now();
        return;
      }
      if (Date.now() - lastProgressAt > FROZEN_AFTER_MS) {
        lastProgressAt = Date.now();
        lastTime = -1;
        scheduleRetry();
      }
    }

    liveEdgeTimer = setInterval(() => {
      jumpToLiveEdge(false);
      checkFrozen();
    }, LIVE_EDGE_CHECK_MS);

    // Brauzer fondagi yorliqda videoni to'xtatadi/sekinlashtiradi, qaytib
    // kelganda esa u o'sha eski nuqtadan davom etadi — devor ochiq turib
    // daqiqalab orqada qolishining eng keng tarqalgan sababi shu.
    onVisible = () => {
      if (document.visibilityState === 'visible') jumpToLiveEdge(true);
    };
    document.addEventListener('visibilitychange', onVisible);

    startTimer = setTimeout(() => {
      if (!cancelled) void start();
    }, startDelayRef.current);

    return () => {
      cancelled = true;
      clearAllTimers();
      if (liveEdgeTimer) clearInterval(liveEdgeTimer);
      if (onVisible) document.removeEventListener('visibilitychange', onVisible);
      teardownPlayback();
      releaseQueueSlot();
    };
  }, [streamUrl, priority, acquireSlot, releaseSlot]);

  if (!streamUrl) return null;

  // DIQQAT: <video> elementi HECH QACHON render daraxtidan chiqarilmaydi.
  // Ilgari `error` holatida butun komponent o'rniga xato matni qaytarilardi;
  // effekt esa qayta urinishda davom etib, DOM'dan chiqib ketgan (React
  // tomonidan ajratilgan) eski elementga ulanardi. Oqim qaytganda
  // `markReady` xato holatini o'chirar, React esa YANGI, bo'sh <video>
  // elementini chizardi — hls.js hamon eskisiga ulangan. Natija: taxminan
  // 3 daqiqalik uzilishdan keyin katak abadiy qora bo'lib qolardi va uni
  // faqat sahifani yangilash tiklardi. Endi xato/kutish holati video
  // ustidagi qatlam sifatida ko'rsatiladi.
  const overlay = error || expired ? 'error' : loading ? 'loading' : null;

  return (
    <>
      {overlay && (
        <div className="absolute inset-0 z-[1] flex flex-col items-center justify-center gap-1.5 bg-black/70">
          {overlay === 'error' ? (
            <>
              <VideoOff size={20} className="text-white/60" />
              <span className="text-[11px] font-medium text-white/60">
                {expired ? "Oqim havolasi muddati tugagan" : "Video oqimini yuklab bo'lmadi"}
              </span>
              <span className="text-[10px] text-white/40">
                {expired ? 'Havola yangilanmoqda...' : 'Qayta urinilmoqda...'}
              </span>
            </>
          ) : (
            <>
              <Loader2 size={22} className="animate-spin text-white/60" />
              {retrying && <span className="text-[10px] font-medium text-white/60">Navbatda...</span>}
            </>
          )}
        </div>
      )}
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={`absolute inset-0 h-full w-full ${fit === 'contain' ? 'object-contain' : 'object-cover'} ${className}`}
      />
      {showDetections && (
        <FaceDetectionOverlay videoRef={videoRef} videoClockRef={videoClockRef} detection={detection.result} fit={fit} />
      )}
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
