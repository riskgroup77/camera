/**
 * Miniatyuralar paneli (CameraThumbnailStrip) uchun ALOHIDA, kichikroq
 * navbat — src/lib/streamLoadQueue.ts (admin panjarasi uchun, MAX
 * 8) bilan bir xil adolatli-aylanish mantig'i, lekin butunlay mustaqil
 * holat bilan, shuning uchun ikkalasi bir-biriga ta'sir qilmaydi.
 *
 * Nega alohida: MonitoringPage'da asosiy kamera (MainCameraView,
 * navbatsiz — priority) HAR DOIM birinchi va darhol ulanishi kerak,
 * shuning uchun u bu navbatga umuman kirmaydi.
 *
 * MAX_CONCURRENT nega aynan THUMBS_PER_PAGE ga teng (kamroq emas):
 * bu panelda kartalar soni O'ZGARMAS va hammasi doim ekranda — 8 ta.
 * Avval bu 4 ga qo'yilgan edi, "bir vaqtda kamroq oqim ochilsin" degan
 * niyat bilan. Amalda bu production'da aynan foydalanuvchi shikoyat
 * qilgan sekinlikni keltirib chiqardi: 5-8-kartalar joy bo'shashini
 * kutardi, joy esa faqat MIN_HOLD_MS (25 soniya) o'tgach aylanardi —
 * ya'ni yarim panel ~25 soniya "Navbatda..." holatida qotib turardi.
 *
 * Aylanish mexanizmi ko'p kartali, scroll qilinadigan panjara uchun
 * (streamLoadQueue.ts) — u yerda kartalar soni joylardan ko'p bo'lishi
 * tabiiy. Bu yerda esa har bir ko'rinadigan karta ochilishi KERAK, va
 * "birdaniga hujum" muammosi navbat bilan emas, CameraThumbnailStrip'dagi
 * bosqichma-bosqich boshlash (MAIN_CAMERA_HEAD_START_MS +
 * THUMBNAIL_STAGGER_MS) bilan hal qilingan: ulanishlar baribir bir
 * lahzada emas, ketma-ket ochiladi. Navbat esa endi faqat kutilmagan
 * holat uchun xavfsizlik to'ri bo'lib qoladi.
 */
const MAX_CONCURRENT = 8;
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
