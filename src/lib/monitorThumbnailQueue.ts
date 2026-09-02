/**
 * Miniatyuralar paneli (CameraThumbnailStrip) uchun ALOHIDA, kichikroq
 * navbat — src/lib/streamLoadQueue.ts (admin panjarasi uchun, MAX
 * 8) bilan bir xil adolatli-aylanish mantig'i, lekin butunlay mustaqil
 * holat bilan, shuning uchun ikkalasi bir-biriga ta'sir qilmaydi.
 *
 * Nega alohida va nega kamroq: MonitoringPage'da asosiy kamera
 * (MainCameraView, navbatsiz — priority) HAR DOIM birinchi va darhol
 * ulanishi kerak. Ilgari miniatyuralar ham hammasi navbatsiz (priority)
 * qilib qo'yilgan edi — nazariy jihatdan "8 tadan oshmaydi" deb
 * o'ylangan edi, lekin bu amalda noto'g'ri bo'lib chiqdi: asosiy + 8
 * miniatyura = 9 ta HAQIQIY video oqimi bir vaqtning o'zida, hech qanday
 * cheklovsiz ulanishga urinardi — production'da bu asosiy kameraning
 * ham "birinchi" bo'lib ochilishini kafolatlamasdi (hammasi tarmoq/server
 * uchun bab-baravar raqobatlashardi) va umuman sekinlashtirardi. Endi:
 * miniatyuralar shu kichikroq (4) navbatdan o'tadi — bir vaqtda ko'pi
 * bilan 4 tasi haqiqatan ulanadi, qolgani streamLoadQueue'dagi bilan bir
 * xil aylanish orqali ("abadiy yuklanib qolmaydi", navbat bilan
 * ulanaveradi), asosiy kamera esa bu navbatga umuman kirmagani uchun har
 * doim darhol, raqobatsiz boshlanadi.
 */
const MAX_CONCURRENT = 4;
const MIN_HOLD_MS = 25_000;
const ROTATION_CHECK_MS = 4_000;

interface Holder {
  id: string;
  revoke: () => void;
  acquiredAt: number;
}

const activeHolders: Holder[] = [];
const waiters: Array<{ id: string; grant: () => void }> = [];
let rotationTimer: ReturnType<typeof setInterval> | null = null;

function grant(id: string, revoke: () => void) {
  activeHolders.push({ id, revoke, acquiredAt: Date.now() });
}

function rotateIfDue() {
  if (waiters.length === 0 || activeHolders.length < MAX_CONCURRENT) return;
  const oldest = activeHolders[0];
  if (Date.now() - oldest.acquiredAt < MIN_HOLD_MS) return;
  activeHolders.shift();
  oldest.revoke();
}

function ensureRotationTimer() {
  if (rotationTimer) return;
  rotationTimer = setInterval(rotateIfDue, ROTATION_CHECK_MS);
}

function stopRotationTimerIfIdle() {
  if (rotationTimer && waiters.length === 0) {
    clearInterval(rotationTimer);
    rotationTimer = null;
  }
}

export function acquireThumbnailSlot(id: string, onRevoked: () => void): Promise<void> {
  if (activeHolders.length < MAX_CONCURRENT) {
    grant(id, onRevoked);
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    waiters.push({
      id,
      grant: () => {
        grant(id, onRevoked);
        resolve();
      },
    });
    ensureRotationTimer();
    rotateIfDue();
  });
}

export function releaseThumbnailSlot(id: string): void {
  const activeIdx = activeHolders.findIndex((h) => h.id === id);
  if (activeIdx !== -1) activeHolders.splice(activeIdx, 1);

  const waiterIdx = waiters.findIndex((w) => w.id === id);
  if (waiterIdx !== -1) waiters.splice(waiterIdx, 1);

  if (activeHolders.length < MAX_CONCURRENT) {
    const next = waiters.shift();
    if (next) next.grant();
  }
  stopRotationTimerIfIdle();
}
