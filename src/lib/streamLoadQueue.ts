/**
 * HLS oqimlar navbati — 'scroll' rejimidagi kartalar uchun. (Devor
 * rejimlari — wall-4/9/16 — bu navbatni butunlay chetlab o'tadi, chunki
 * foydalanuvchi aynan shu N ta kamerani bir vaqtda ko'rishni tanlagan.)
 *
 * Oldingi versiya joy(slot)ni faqat komponent unmount bo'lganda
 * bo'shatardi — scroll rejimida odatda ishlaydi (ekrandan chiqqan karta
 * unmount bo'ladi), LEKIN agar bitta paytda MAX_CONCURRENT'dan ko'proq
 * karta bir vaqtning o'zida ko'rinadigan bo'lsa (keng ekranda ko'p
 * ustunli panjara), navbatdagi ortiqcha kartalar hech qachon o'z
 * navbatiga yetmasdi — abadiy "yuklanmoqda"/qora holatda qolardi.
 *
 * Endi: MIN_HOLD_MS dan ko'proq vaqt joy egallab turgan eng eski karta,
 * agar navbatda kutayotganlar bo'lsa, MAJBURAN bo'shatiladi (revoke) —
 * shuning uchun hozir ko'rinadigan HAR BIR kartaga, navbat bilan bo'lsa
 * ham, ertami-kechmi o'z ulanish payti yetadi. Chetlatilgan tomon buni
 * xato emas, oddiy "joy bering" signali sifatida qabul qilib, hali ham
 * ko'rinib turgan bo'lsa, qayta navbatga turishi kerak (LiveVideoPlayer'ga
 * qarang).
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
  oldest.revoke(); // caller tears down and calls releaseStreamSlot(id), which promotes the next waiter
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

/**
 * id: barqaror identifikator (masalan stream URL) — chetlatilgandan keyin
 * qayta so'ralganda va scroll-out paytida navbatdan olib tashlashda kerak.
 * onRevoked: joy boshqa (navbatda kutayotgan) kartaga berish uchun
 * majburan bo'shatilganda chaqiriladi.
 */
export function acquireStreamSlot(id: string, onRevoked: () => void): Promise<void> {
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

/** Joyni bo'shatadi — ham faol egallovchi, ham hali navbatda kutayotgan
 * (masalan foydalanuvchi o'z navbatiga yetmasdan oldin scroll qilib
 * chiqib ketgan) holat uchun ishlaydi. */
export function releaseStreamSlot(id: string): void {
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

export function streamQueueStats(): { active: number; waiting: number } {
  return { active: activeHolders.length, waiting: waiters.length };
}
