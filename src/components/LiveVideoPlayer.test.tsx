import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import LiveVideoPlayer, { streamRetryDelay } from './LiveVideoPlayer';

vi.mock('../lib/useLiveDetection', () => ({ useLiveDetection: () => ({ result: null, slotDenied: false }) }));

/** hls.js o'rniga — brauzer video steki vitest'da yo'q, lekin pleyerning
 *  xatolarga MUNOSABATI aynan shu yerda hal bo'ladi, shuning uchun soxta
 *  instansiya hodisalarni qo'lda yuborishga imkon beradi. */
type HlsHandler = (event: string, data: Record<string, unknown>) => void;
const hlsInstances: FakeHls[] = [];

class FakeHls {
  static Events = { MANIFEST_PARSED: 'hlsManifestParsed', FRAG_BUFFERED: 'hlsFragBuffered', ERROR: 'hlsError' };
  static ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' };
  static isSupported = () => true;
  handlers = new Map<string, HlsHandler[]>();
  destroyed = false;
  loadSource = vi.fn();
  attachMedia = vi.fn();
  startLoad = vi.fn();
  recoverMediaError = vi.fn();
  constructor() {
    hlsInstances.push(this);
  }
  on(event: string, cb: HlsHandler) {
    const list = this.handlers.get(event) ?? [];
    list.push(cb);
    this.handlers.set(event, list);
  }
  destroy() {
    this.destroyed = true;
  }
  emit(event: string, data: Record<string, unknown> = {}) {
    for (const cb of this.handlers.get(event) ?? []) cb(event, data);
  }
}

vi.mock('hls.js', () => ({ default: FakeHls }));

/** <video> elementiga qo'yilgan va olib tashlangan tinglovchilar.
 *  React'ning o'zi ham mount paytida media hodisalarini elementga
 *  bog'laydi, shuning uchun sanoq har doim "shu paytdan keyin"
 *  (`since`) olinadi. */
let added: string[] = [];
let removed: string[] = [];
const origAdd = HTMLMediaElement.prototype.addEventListener;
const origRemove = HTMLMediaElement.prototype.removeEventListener;

beforeEach(() => {
  added = [];
  removed = [];
  hlsInstances.length = 0;
  HTMLMediaElement.prototype.addEventListener = function patchedAdd(
    this: HTMLMediaElement,
    ...args: Parameters<HTMLElement['addEventListener']>
  ) {
    added.push(args[0]);
    return origAdd.apply(this, args);
  };
  HTMLMediaElement.prototype.removeEventListener = function patchedRemove(
    this: HTMLMediaElement,
    ...args: Parameters<HTMLElement['removeEventListener']>
  ) {
    removed.push(args[0]);
    return origRemove.apply(this, args);
  };
  // jsdom'da play()/load() yo'q — pleyerning o'z xato yo'li sinovga aloqasiz.
  HTMLMediaElement.prototype.play = vi.fn(async () => {});
  HTMLMediaElement.prototype.load = vi.fn();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  HTMLMediaElement.prototype.addEventListener = origAdd;
  HTMLMediaElement.prototype.removeEventListener = origRemove;
});

const since = (list: string[], from: number, type: string) => list.slice(from).filter((item) => item === type).length;

/** Katak almashganda yoki yon paneldagi tanlov o'zgarganda pleyer
 *  unmount bo'ladi. O'shanda <video> elementiga qo'yilgan hamma narsa
 *  yig'ishtirilishi kerak: `{ once: true }` tinglovchini FAQAT u ishga
 *  tushsa o'chiradi, oqim ishga tushmayotgan kamerada esa u hech qachon
 *  ishlamaydi va har qayta urinishda yangisi ustiga qo'shilib borardi. */
describe('LiveVideoPlayer — tozalash', () => {
  it('unmount qilinganda video tinglovchilari olib tashlanadi', async () => {
    const view = render(<LiveVideoPlayer streamUrl="https://cam.example/s0/cam-1/index.mp4" priority />);
    const afterMount = added.length;

    // startDelay (0 ms) o'tadi va attach() ishlaydi.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(since(added, afterMount, 'playing')).toBe(1);
    expect(since(added, afterMount, 'loadeddata')).toBe(1);

    const beforeUnmount = removed.length;
    view.unmount();
    expect(since(removed, beforeUnmount, 'playing')).toBe(1);
    expect(since(removed, beforeUnmount, 'loadeddata')).toBe(1);
  });

  it("qayta urinish har safar yangi tinglovchi to'plamaydi", async () => {
    const view = render(<LiveVideoPlayer streamUrl="https://cam.example/s0/cam-1/index.mp4" priority />);
    const afterMount = added.length;
    const fromStart = removed.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(since(added, afterMount, 'playing')).toBe(1);

    // Yuklash kutish vaqti (30 s) tugadi -> qayta urinish rejalashtiriladi,
    // backoff (≈8 s) o'tgach yangi attach() bo'ladi.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    const adds = since(added, afterMount, 'playing');
    expect(adds).toBeGreaterThan(1);
    // Har yangi ulanishdan OLDIN eskisi olib tashlangan: to'planib qolmaydi.
    expect(since(removed, fromStart, 'playing')).toBe(adds - 1);

    view.unmount();
    expect(since(removed, fromStart, 'playing')).toBe(adds);
  });
});

/** Uzun uzilishdan keyingi tiklanish. Situatsion markaz televizori kunlab
 *  qarovsiz ishlaydi: kamera qayta yuklanishi, MediaMTX'ning yo'lni
 *  yangilashi yoki tarmoq uzilishi bir necha daqiqa davom etishi mumkin.
 *  Shundan keyin oqim qaytganda katak O'ZI tiklanishi shart. */
describe('LiveVideoPlayer — uzoq uzilish', () => {
  it("xato holatida ham <video> elementi saqlanadi (aynan o'sha element)", async () => {
    const view = render(<LiveVideoPlayer streamUrl="https://cam.example/s0/cam-1/index.mp4" priority />);
    const first = view.container.querySelector('video');
    expect(first).not.toBeNull();

    // SHOW_ERROR_AFTER_ATTEMPTS (10) ta muvaffaqiyatsiz aylanish:
    // har biri 30 s kutish + 8..20 s backoff.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(520_000);
    });

    expect(view.container.textContent).toContain("Video oqimini yuklab bo'lmadi");
    // Ilgari bu yerda komponent <video> o'rniga faqat xato matnini
    // qaytarardi: hls.js/effekt ajratilgan elementga ulanib qolar va
    // oqim qaytganda katak abadiy qora bo'lib qolardi.
    const stillThere = view.container.querySelector('video');
    expect(stillThere).not.toBeNull();
    expect(stillThere).toBe(first);

    view.unmount();
  });
});

describe('LiveVideoPlayer — imzolangan havola (403)', () => {
  it('muddati tugagan havolada halol holat ko‘rsatadi va yangi havola so‘raydi', async () => {
    const onStreamUnavailable = vi.fn();
    const view = render(
      <LiveVideoPlayer
        streamUrl="https://cam.example/s0/cam-1/index.m3u8"
        priority
        onStreamUnavailable={onStreamUnavailable}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(hlsInstances).toHaveLength(1);

    await act(async () => {
      hlsInstances[0].emit(FakeHls.Events.ERROR, {
        type: FakeHls.ErrorTypes.NETWORK_ERROR,
        fatal: true,
        response: { code: 403 },
      });
    });

    // nginx imzoni rad etdi — AYNAN shu manzilni qayta so'rash foydasiz,
    // egasidan yangi imzolangan havola so'raladi.
    expect(onStreamUnavailable).toHaveBeenCalled();
    expect(view.container.textContent).toContain('muddati tugagan');
    // Tez ketma-ket qayta urinish YO'Q — serverni bezovta qilmaymiz.
    expect(hlsInstances[0].startLoad).not.toHaveBeenCalled();
    expect(view.container.querySelector('video')).not.toBeNull();

    view.unmount();
  });
});

/** Bir vaqtda o'nlab oqim yiqilganda (MediaMTX shardi qayta ishga tushdi,
 *  tarmoq bir zumga uzildi) kataklar QAT'IY bir xil vaqtda qayta
 *  urinmasligi kerak: aks holda server ko'tarilishi bilan devordagi 16 ta
 *  katak (va har bir televizor) bir zumda hammasi birdan ulanadi va
 *  shardni qaytadan bo'g'adi. Xuddi shu muammo WebSocket ulanishida
 *  allaqachon tasodifiy qo'shimcha bilan hal qilingan (realtime.ts). */
describe('LiveVideoPlayer — qayta ulanish bo‘roni', () => {
  it('kutish vaqti tasodifiy qo‘shimcha bilan yoyiladi', () => {
    // Bir xil urinish raqami — lekin bir xil vaqt EMAS.
    expect(streamRetryDelay(1, () => 0)).toBe(6400);
    expect(streamRetryDelay(1, () => 1)).toBe(9600);
    // Chegara ham yoyiladi, lekin o'sish saqlanadi.
    expect(streamRetryDelay(50, () => 0.5)).toBe(20_000);
  });

  it('bir vaqtda yiqilgan ikki oqim bir vaqtda qayta urinmaydi', async () => {
    // Birinchi pleyer eng qisqa, ikkinchisi eng uzun kutishni oladi.
    const values = [0, 1];
    let call = 0;
    const random = vi.spyOn(Math, 'random').mockImplementation(() => values[call++ % values.length]);

    const urlA = 'https://cam.example/s0/cam-a/index.m3u8';
    const urlB = 'https://cam.example/s0/cam-b/index.m3u8';
    const a = render(<LiveVideoPlayer streamUrl={urlA} priority />);
    const b = render(<LiveVideoPlayer streamUrl={urlB} priority />);
    const attempts = (url: string) =>
      hlsInstances.filter((instance) => instance.loadSource.mock.calls[0]?.[0] === url).length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(attempts(urlA)).toBe(1);
    expect(attempts(urlB)).toBe(1);

    // Ikkalasi ham bir zumda yiqiladi (yuklash kutish vaqti tugadi).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });

    // Qat'iy backoff bilan ikkalasi ham aynan 8000 ms da qaytardi.
    // Yoyilgan kutish bilan bu oraliqda faqat BIRINCHISI qaytadi.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(7_000);
    });
    expect(attempts(urlA)).toBe(2);
    expect(attempts(urlB)).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(attempts(urlB)).toBe(2);

    random.mockRestore();
    a.unmount();
    b.unmount();
  });
});

/** Qotib qolish nazorati hls.js ISHLATILMAGAN yo'llarda ham ishlashi kerak:
 *  Safari/iOS o'z HLS pleyerini ishlatadi, MP4/WebM manbada esa hls.js
 *  umuman yo'q — aynan o'sha yerda qotgan tasvir eng uzoq ko'rinib turardi. */
describe('LiveVideoPlayer — qotib qolish nazorati', () => {
  const props = ['readyState', 'videoWidth', 'currentTime', 'paused'] as const;
  const saved: Record<string, PropertyDescriptor | undefined> = {};

  function stubPlayback({ currentTime }: { currentTime: () => number }) {
    for (const name of props) {
      saved[name] = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, name);
    }
    Object.defineProperty(HTMLVideoElement.prototype, 'readyState', { configurable: true, get: () => 4 });
    Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 1280 });
    Object.defineProperty(HTMLVideoElement.prototype, 'paused', { configurable: true, get: () => false });
    Object.defineProperty(HTMLVideoElement.prototype, 'currentTime', {
      configurable: true,
      get: currentTime,
      set: () => {},
    });
  }

  afterEach(() => {
    for (const name of props) {
      if (saved[name]) Object.defineProperty(HTMLVideoElement.prototype, name, saved[name]!);
      else delete (HTMLVideoElement.prototype as unknown as Record<string, unknown>)[name];
    }
  });

  it('hls.js ishlatilmasa ham qotgan oqimni qayta ulaydi', async () => {
    stubPlayback({ currentTime: () => 5 }); // vaqt siljimaydi — oqim qotgan
    const view = render(<LiveVideoPlayer streamUrl="https://cam.example/s0/cam-1/index.mp4" priority />);
    const afterMount = added.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(since(added, afterMount, 'playing')).toBe(1);

    // FROZEN_AFTER_MS (8 s) + backoff (≈8 s) — qayta ulanish bo'lishi kerak.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(22_000);
    });
    expect(since(added, afterMount, 'playing')).toBeGreaterThan(1);

    view.unmount();
  });

  it("sog'lom oqimda bekorga ishga tushmaydi", async () => {
    let t = 0;
    stubPlayback({ currentTime: () => (t += 0.5) });
    const view = render(<LiveVideoPlayer streamUrl="https://cam.example/s0/cam-1/index.mp4" priority />);
    const afterMount = added.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(25_000);
    });
    expect(since(added, afterMount, 'playing')).toBe(1);

    view.unmount();
  });
});
