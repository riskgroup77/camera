import { beforeEach, describe, expect, it } from 'vitest';
import { cameraIdFromStreamUrl, noteWebrtcResult, webrtcAllowed } from './webrtcStream';
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
