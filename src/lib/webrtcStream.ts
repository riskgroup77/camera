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
const ICE_GATHER_MS = 1200;
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
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', check);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === 'complete') done();
    };
    pc.addEventListener('icegatheringstatechange', check);
    setTimeout(done, ICE_GATHER_MS);
  });
}

/** WebRTC ulanishini ochib, videoni `video` elementiga ulaydi. Tasvir
 *  kelmasa yoki server rad etsa — xato tashlaydi (chaqiruvchi HLS'ga o'tadi). */
export async function startWebrtc(cameraId: string, video: HTMLVideoElement, signal?: AbortSignal): Promise<WebrtcSession> {
  const pc = new RTCPeerConnection({ bundlePolicy: 'max-bundle' });
  const failureCallbacks: Array<() => void> = [];
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    pc.close();
    if (video.srcObject) video.srcObject = null;
  };
  signal?.addEventListener('abort', close);

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
    // Kechikishni minimal ushlash — brauzer jitter buferini kichik tutadi.
    for (const receiver of pc.getReceivers()) {
      const tuned = receiver as RTCRtpReceiver & { jitterBufferTarget?: number | null };
      if ('jitterBufferTarget' in tuned) tuned.jitterBufferTarget = 0;
    }
    video.srcObject = stream;
    pc.addEventListener('connectionstatechange', () => {
      if (!closed && (pc.connectionState === 'failed' || pc.connectionState === 'disconnected')) {
        failureCallbacks.forEach((callback) => callback());
      }
    });
    return { close, onFailure: (callback) => failureCallbacks.push(callback) };
  } catch (error) {
    close();
    throw error;
  }
}
