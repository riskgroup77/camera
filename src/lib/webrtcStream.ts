import { apiUrl, getAccessToken } from './apiClient';

/**
 * Jonli video WebRTC orqali (WHEP) — kechikish ~0.3-0.5 s (HLS'da 4-8 s edi).
 *
 * Brauzer SDP taklifini API'ga yuboradi (POST /api/public/cameras/{id}/whep,
 * odatdagi login bilan), API uni kamera turgan MediaMTX shard'iga uzatadi.
 * Media UDP'da to'g'ridan-to'g'ri keladi — u faqat LAN'da ochiq. Tashqi
 * tarmoqdan yoki UDP bloklangan joydan ulanish bo'lmaydi: bunday holda
 * pleyer HLS'ga qaytadi va bir muddat WebRTC'ni qayta sinamaydi
 * (`webrtcAllowed`), aks holda har katak 6 s bekor kutardi.
 */

const CONNECT_TIMEOUT_MS = 6000;
/** ICE nomzodlarini kutishning yuqori chegarasi. */
const ICE_GATHER_MS = 1200;
/** Birinchi nomzoddan keyin shuncha kutib taklif yuboriladi. LAN'da hamma
 *  "host" nomzodlar bir zumda chiqadi — to'liq yig'ilishni (ba'zan 1.2 s)
 *  kutish ulanishni behuda kechiktirardi. */
export const ICE_SETTLE_MS = 150;
/** Oldindan ochilgan (xona kartasi ustida turilganda) ulanish shuncha vaqt
 *  ishlatilmasa yopiladi. */
export const PREWARM_TTL_MS = 8000;
/** Brauzer jitter buferi (ms). 0 da LAN'dagi har tebranish (Wi-Fi, server
 *  yuklamasi) tasvirni "tutilib-tutilib" ko'rsatardi; operator 2-3 s
 *  kechikishga rozi, silliqlik muhimroq. Yuz ramkalari shu qiymatga
 *  tuzatiladi (WEBRTC_VIDEO_DELAY_MS). */
export const WEBRTC_JITTER_BUFFER_MS = 300;
/** WebRTC videosi server soatidan taxminan shuncha orqada (bufer + tarmoq). */
export const WEBRTC_VIDEO_DELAY_MS = WEBRTC_JITTER_BUFFER_MS + 100;
/** "disconnected" ko'pincha o'tkinchi (ICE o'zi tiklanadi) — shuncha kutib,
 *  tiklanmasa qayta ulanamiz. "failed" — darhol. */
export const DISCONNECT_GRACE_MS = 4000;
/** Ketma-ket shuncha muvaffaqiyatsizlikdan keyin WebRTC vaqtincha o'chadi. */
const FAILURES_BEFORE_PAUSE = 2;
const PAUSE_MS = 10 * 60_000;
const STORAGE_KEY = 'webrtc-paused-until';

let consecutiveFailures = 0;

/** Kamera identifikatori oqim manzilidan: `.../cam-<uuid>/index.m3u8`. */
export function cameraIdFromStreamUrl(url: string | null | undefined): string | null {
  const match = url?.match(/\/cam-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\//i);
  return match ? match[1] : null;
}

function pausedUntil(): number {
  try {
    return Number(localStorage.getItem(STORAGE_KEY) || 0);
  } catch {
    return 0;
  }
}

export function webrtcAllowed(): boolean {
  return typeof RTCPeerConnection !== 'undefined' && Date.now() >= pausedUntil();
}

export function noteWebrtcResult(ok: boolean): void {
  if (ok) {
    consecutiveFailures = 0;
    return;
  }
  consecutiveFailures += 1;
  if (consecutiveFailures >= FAILURES_BEFORE_PAUSE) {
    consecutiveFailures = 0;
    try {
      localStorage.setItem(STORAGE_KEY, String(Date.now() + PAUSE_MS));
    } catch {
      // saqlab bo'lmasa — keyingi safar yana sinaladi
    }
  }
}

export interface WebrtcSession {
  close(): void;
  /** Ulanish uzilsa (ICE failed/closed) chaqiriladi. */
  onFailure(callback: () => void): void;
}

function waitForIce(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    let settle: ReturnType<typeof setTimeout> | null = null;
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', check);
      pc.removeEventListener('icecandidate', onCandidate);
      if (settle) clearTimeout(settle);
      clearTimeout(cap);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === 'complete') done();
    };
    const onCandidate = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate && settle === null) settle = setTimeout(done, ICE_SETTLE_MS);
    };
    pc.addEventListener('icegatheringstatechange', check);
    pc.addEventListener('icecandidate', onCandidate);
    const cap = setTimeout(done, ICE_GATHER_MS);
  });
}

interface Negotiated {
  pc: RTCPeerConnection;
  stream: MediaStream;
}

/** Taklif -> WHEP -> javob -> birinchi trek va "connected". Videoga ulamaydi:
 *  natijani oldindan ochish (prewarmWebrtc) ham, pleyer ham ishlatadi. */
async function negotiate(cameraId: string, signal?: AbortSignal): Promise<Negotiated> {
  const pc = new RTCPeerConnection({ bundlePolicy: 'max-bundle' });
  const abort = () => pc.close();
  signal?.addEventListener('abort', abort);
  try {
    pc.addTransceiver('video', { direction: 'recvonly' });
    const firstTrack = new Promise<MediaStream>((resolve) => {
      pc.addEventListener('track', (event) => resolve(event.streams[0] ?? new MediaStream([event.track])));
    });
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIce(pc);

    const token = getAccessToken();
    const response = await fetch(apiUrl(`/api/public/cameras/${cameraId}/whep`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: pc.localDescription?.sdp ?? '',
      credentials: 'include',
      signal,
    });
    if (!response.ok) throw new Error(`WHEP ${response.status}`);
    await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() });

    const stream = await Promise.race([
      firstTrack,
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('WebRTC: tasvir kelmadi')), CONNECT_TIMEOUT_MS)),
    ]);
    const connected = new Promise<void>((resolve, reject) => {
      const check = () => {
        if (pc.connectionState === 'connected') resolve();
        else if (pc.connectionState === 'failed' || pc.connectionState === 'closed') reject(new Error('WebRTC: ulanmadi'));
      };
      pc.addEventListener('connectionstatechange', check);
      check();
      setTimeout(() => reject(new Error('WebRTC: ulanish vaqti tugadi')), CONNECT_TIMEOUT_MS);
    });
    await connected;
    return { pc, stream };
  } catch (error) {
    pc.close();
    throw error;
  } finally {
    signal?.removeEventListener('abort', abort);
  }
}

// ── Oldindan ochish: operator xona kartasi ustida turganda ulanish
// boshlanadi, bosganda tayyor ulanish darhol videoga beriladi (~0.5-1 s
// tejaladi). Bir vaqtda bittasi; ishlatilmasa PREWARM_TTL_MS da yopiladi.
let warm: { cameraId: string; promise: Promise<Negotiated>; controller: AbortController; timer: ReturnType<typeof setTimeout> } | null = null;

function dropWarm(): void {
  if (!warm) return;
  const stale = warm;
  warm = null;
  clearTimeout(stale.timer);
  stale.controller.abort();
  stale.promise.then(({ pc }) => pc.close(), () => undefined);
}

export function prewarmWebrtc(cameraId: string): void {
  if (!webrtcAllowed() || warm?.cameraId === cameraId) return;
  dropWarm();
  const controller = new AbortController();
  const promise = negotiate(cameraId, controller.signal);
  const entry = { cameraId, promise, controller, timer: setTimeout(dropWarm, PREWARM_TTL_MS) };
  warm = entry;
  // Muvaffaqiyatsiz oldindan ochish jim o'tadi — pleyer o'zi ulanadi.
  promise.catch(() => {
    if (warm === entry) {
      clearTimeout(entry.timer);
      warm = null;
    }
  });
}

function takeWarm(cameraId: string): Promise<Negotiated> | null {
  if (!warm || warm.cameraId !== cameraId) return null;
  const taken = warm;
  warm = null;
  clearTimeout(taken.timer);
  return taken.promise;
}

/** Testlar uchun. */
export function resetPrewarmForTests(): void {
  dropWarm();
}

/** WebRTC ulanishini ochib (yoki oldindan ochilganini olib), videoni
 *  `video` elementiga ulaydi. Tasvir kelmasa yoki server rad etsa — xato
 *  tashlaydi (chaqiruvchi HLS'ga o'tadi). */
export async function startWebrtc(cameraId: string, video: HTMLVideoElement, signal?: AbortSignal): Promise<WebrtcSession> {
  let negotiated: Negotiated | null = null;
  const prepared = takeWarm(cameraId);
  if (prepared) {
    negotiated = await prepared.catch(() => null);
    if (negotiated && negotiated.pc.connectionState !== 'connected') {
      negotiated.pc.close();
      negotiated = null;
    }
  }
  negotiated ??= await negotiate(cameraId, signal);
  const { pc, stream } = negotiated;
  const failureCallbacks: Array<() => void> = [];
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    pc.close();
    if (video.srcObject) video.srcObject = null;
  };
  if (signal?.aborted) {
    close();
    throw new DOMException('Bekor qilindi', 'AbortError');
  }
  signal?.addEventListener('abort', close);

  try {
    for (const receiver of pc.getReceivers()) {
      const tuned = receiver as RTCRtpReceiver & { jitterBufferTarget?: number | null };
      if ('jitterBufferTarget' in tuned) tuned.jitterBufferTarget = WEBRTC_JITTER_BUFFER_MS;
    }
    video.srcObject = stream;
    let graceTimer: ReturnType<typeof setTimeout> | null = null;
    const fail = () => {
      if (graceTimer) clearTimeout(graceTimer);
      graceTimer = null;
      if (!closed) failureCallbacks.forEach((callback) => callback());
    };
    pc.addEventListener('connectionstatechange', () => {
      if (closed) return;
      if (pc.connectionState === 'failed') fail();
      else if (pc.connectionState === 'disconnected') {
        // Ilgari darhol uzib, 6-8 s dan keyin qayta ulanardi — bir
        // soniyalik Wi-Fi tebranishi ham tasvirni qotirib qo'yardi.
        graceTimer ??= setTimeout(fail, DISCONNECT_GRACE_MS);
      } else if (pc.connectionState === 'connected' && graceTimer) {
        clearTimeout(graceTimer);
        graceTimer = null;
      }
    });
    signal?.addEventListener('abort', () => {
      if (graceTimer) clearTimeout(graceTimer);
    });
    return { close, onFailure: (callback) => failureCallbacks.push(callback) };
  } catch (error) {
    close();
    throw error;
  }
}
