import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** Modul holati global — har sinov uchun toza nusxa. */
async function freshQueue() {
  vi.resetModules();
  return import('./streamLoadQueue');
}

describe('streamLoadQueue — adolatli navbat', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('chetlatilgan karta joyni kutayotganga beradi (o\'zi qaytarib olmaydi)', async () => {
    const { acquireStreamSlot, streamQueueStats } = await freshQueue();

    // 8 ta joy to'lgan. Har biri LiveVideoPlayer kabi: chetlatilsa —
    // darhol qayta navbatga turadi.
    for (let i = 0; i < 8; i += 1) {
      const id = `holder-${i}`;
      const requeue = () => {
        void acquireStreamSlot(id, requeue);
      };
      await acquireStreamSlot(id, requeue);
    }
    expect(streamQueueStats()).toEqual({ active: 8, waiting: 0 });

    let granted = false;
    void acquireStreamSlot('kutayotgan', () => {}).then(() => {
      granted = true;
    });
    expect(streamQueueStats().waiting).toBe(1);

    // MIN_HOLD_MS (25s) o'tgach, aylanish taymeri (4s) eng eskisini chetlatadi.
    await vi.advanceTimersByTimeAsync(30_000);

    expect(granted).toBe(true);
    expect(streamQueueStats().active).toBe(8);
  });

  it("bir xil id bilan kutayotgan karta egasining bo'shatishida navbatdan tushib qolmaydi", async () => {
    const { acquireStreamSlot, releaseStreamSlot, streamQueueStats } = await freshQueue();

    for (let i = 0; i < 8; i += 1) await acquireStreamSlot(`s${i}`, () => {});

    // Xuddi shu oqim manzili ikkinchi marta so'raladi (masalan bitta
    // kamera devorga ikki marta qo'yilgan) — u navbatda kutadi.
    let granted = false;
    void acquireStreamSlot('s0', () => {}).then(() => {
      granted = true;
    });
    expect(streamQueueStats().waiting).toBe(1);

    // Egasi joyni bo'shatadi: navbatdagi nusxa GRANT olishi kerak,
    // jimgina navbatdan o'chirilib qolmasligi kerak.
    releaseStreamSlot('s0');
    await Promise.resolve();

    expect(granted).toBe(true);
    expect(streamQueueStats()).toEqual({ active: 8, waiting: 0 });
  });

  it("navbatdan chiqarilgan kutuvchining promise'i osilib qolmaydi", async () => {
    const { acquireStreamSlot, releaseStreamSlot, streamQueueStats } = await freshQueue();

    for (let i = 0; i < 8; i += 1) await acquireStreamSlot(`h${i}`, () => {});

    // Karta o'z navbatiga YETMASDAN ekrandan chiqdi (setka almashdi,
    // katak kattalashtirildi, tur keyingi ko'rinishga o'tdi).
    const waiting = acquireStreamSlot('kutayotgan', () => {});
    expect(streamQueueStats().waiting).toBe(1);
    releaseStreamSlot('kutayotgan');
    expect(streamQueueStats().waiting).toBe(0);

    // Promise hal bo'lishi SHART: aks holda uni kutayotgan `start()`
    // funksiyasi (va u ushlab turgan butun effekt yopilmasi — <video>,
    // hls.js instansiyasi, kamera ma'lumoti) varaq umri davomida
    // xotirada osilib qolardi. Soatlab ochiq turadigan devorda setka har
    // almashganda shunday "o'lik" yopilmalar to'planib borardi.
    const outcome = await Promise.race([
      waiting.then(() => 'settled'),
      new Promise((resolve) => setTimeout(() => resolve('hung'), 50)),
    ]);
    expect(outcome).toBe('settled');
  });
});
