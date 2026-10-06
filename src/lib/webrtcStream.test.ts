import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cameraIdFromStreamUrl,
  noteWebrtcResult,
  prewarmWebrtc,
  resetPrewarmForTests,
  startWebrtc,
  webrtcAllowed,
} from './webrtcStream';
import { noteServerTime, resetServerClockForTests, serverNow } from './serverClock';

describe('cameraIdFromStreamUrl', () => {
  it('imzoli va imzosiz manzildan kamera identifikatori', () => {
    const id = '92b6d6ac-6ffd-417d-8b3e-37479172a700';
    expect(cameraIdFromStreamUrl(`/s0/cam-${id}/index.m3u8`)).toBe(id);
    expect(cameraIdFromStreamUrl(`https://cam.fermi.uz/s2/HWUn_x,1790316000/cam-${id}/index.m3u8`)).toBe(id);
    expect(cameraIdFromStreamUrl('/video.mp4')).toBeNull();
  });
});

describe('webrtc pause', () => {
  beforeEach(() => {
    localStorage.clear();
    (globalThis as { RTCPeerConnection?: unknown }).RTCPeerConnection = class {};
  });

  it("ikki ketma-ket muvaffaqiyatsizlikdan keyin vaqtincha HLS'ga o'tadi", () => {
    expect(webrtcAllowed()).toBe(true);
    noteWebrtcResult(false);
    expect(webrtcAllowed()).toBe(true);
    noteWebrtcResult(false);
    expect(webrtcAllowed()).toBe(false);
  });

  it('muvaffaqiyat hisobni nolga qaytaradi', () => {
    noteWebrtcResult(false);
    noteWebrtcResult(true);
    noteWebrtcResult(false);
    expect(webrtcAllowed()).toBe(true);
  });
});

describe('serverClock', () => {
  beforeEach(() => resetServerClockForTests());

  it("server soatini borib-kelish vaqtining yarmi bilan hisoblaydi", () => {
    const now = Date.now();
    // Server soati brauzerdan 5 s oldinda, so'rov 200 ms.
    noteServerTime((now + 100 + 5000) / 1000, now, now + 200);
    expect(Math.abs(serverNow() - (Date.now() + 5000))).toBeLessThan(50);
  });

  it("uzoqroq borib-kelishli o'lchov aniqrog'ini almashtirmaydi", () => {
    const now = Date.now();
    noteServerTime((now + 50) / 1000, now, now + 100);
    noteServerTime((now + 10_000) / 1000, now, now + 3000);
    expect(Math.abs(serverNow() - Date.now())).toBeLessThan(50);
  });
});

describe('oldindan ochilgan WebRTC ulanishi', () => {
  type Listener = (event: unknown) => void;
  const created: FakePc[] = [];
  const stream = { id: 'stream' };
  class FakePc {
    connectionState = 'new';
    iceGatheringState = 'complete';
    localDescription: { sdp: string } | null = null;
    closed = false;
    private listeners: Record<string, Listener[]> = {};
    constructor() {
      created.push(this);
    }
    addTransceiver() {}
    async createOffer() {
      return { type: 'offer', sdp: 'v=0' };
    }
    async setLocalDescription() {
      this.localDescription = { sdp: 'v=0\r\noffer' };
    }
    async setRemoteDescription() {
      setTimeout(() => {
        this.emit('track', { streams: [stream] });
        this.connectionState = 'connected';
        this.emit('connectionstatechange', {});
      }, 0);
    }
    getReceivers() {
      return [];
    }
    close() {
      this.closed = true;
      this.connectionState = 'closed';
    }
    addEventListener(type: string, callback: Listener) {
      (this.listeners[type] ??= []).push(callback);
    }
    removeEventListener(type: string, callback: Listener) {
      this.listeners[type] = (this.listeners[type] ?? []).filter((item) => item !== callback);
    }
    emit(type: string, event: unknown) {
      (this.listeners[type] ?? []).forEach((callback) => callback(event));
    }
  }

  beforeEach(() => {
    localStorage.clear();
    created.length = 0;
    resetPrewarmForTests();
    (globalThis as { RTCPeerConnection?: unknown }).RTCPeerConnection = FakePc;
    vi.stubGlobal('fetch', vi.fn(async () => new Response('v=0\r\nanswer', { status: 201 })));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("bosilganda oldindan ochilgan ulanish ishlatiladi (qayta muzokara yo'q)", async () => {
    prewarmWebrtc('cam-1');
    await new Promise((resolve) => setTimeout(resolve, 5));
    const video = document.createElement('video');
    await startWebrtc('cam-1', video);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(created).toHaveLength(1);
    expect(video.srcObject).toBe(stream);
  });

  it('boshqa kamera tanlansa oldindan ochilgani yopiladi va yangisi ulanadi', async () => {
    prewarmWebrtc('cam-1');
    await new Promise((resolve) => setTimeout(resolve, 5));
    prewarmWebrtc('cam-2');
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(created[0].closed).toBe(true);
    await startWebrtc('cam-3', document.createElement('video'));
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});
