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
/** `cancel` — joy berilmasdan navbatdan chiqarilganda promise'ni hal qiladi.
 * Busiz kutayotgan karta unmount bo'lganda uning `await acquireStreamSlot(...)`
 * i ABADIY osilib qolardi: to'xtatilgan `start()` funksiyasi (va u ushlab
 * turgan butun effekt yopilmasi — video element, hls instansiyasi, kamera
 * ma'lumoti) varaq umri davomida xotirada qolardi. Soatlab ochiq turadigan
 * situatsion markaz ekranida, setka har almashganda, shunday "o'lik" yopilmalar
 * to'planib borardi. */
const waiters: Array<{ id: string; grant: () => void; cancel: () => void }> = [];
let rotationTimer: ReturnType<typeof setInterval> | null = null;

function grant(id: string, revoke: () => void) {
  activeHolders.push({ id, revoke, acquiredAt: Date.now() });
}

function rotateIfDue() {
  if (waiters.length === 0 || activeHolders.length < MAX_CONCURRENT) return;
  const oldest = activeHolders[0];
  if (Date.now() - oldest.acquiredAt < MIN_HOLD_MS) return;
  activeHolders.shift();
  // Joyni AVVAL kutayotganga beramiz, keyin chetlatamiz. Aks holda
  // chetlatilgan tomon (LiveVideoPlayer.onRevoked) darhol, o'sha
  // chaqiruv ichida qayta `acquireStreamSlot` qiladi va endigina
  // bo'shagan joyni o'ziga qaytarib oladi — navbatdagilar abadiy
  // kutib qolardi, ko'rinib turgan kartalar esa har 4 soniyada
  // bekorga uzilib-ulanib turardi.
  const next = waiters.shift();
  if (next) next.grant();
  oldest.revoke();
  stopRotationTimerIfIdle();
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
      cancel: resolve,
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
  if (activeIdx !== -1) {
    activeHolders.splice(activeIdx, 1);
  } else {
    // FAQAT egasi bo'lmaganda navbatdan olib tashlaymiz. Ilgari ikkalasi
    // ham bajarilardi: bir xil manzil ikki joyda ishlatilganda (bitta
    // kamera devorda ikki marta) egasining bo'shatishi navbatdagi
    // nusxani ham jimgina o'chirib yuborardi — uning promise'i hech
    // qachon hal bo'lmay, karta abadiy "Navbatda..." holatida qolardi.
    const waiterIdx = waiters.findIndex((w) => w.id === id);
    // Promise'ni JOY BERMASDAN hal qilamiz: chaqiruvchi (LiveVideoPlayer.start)
    // uyg'onib, o'zining `cancelled` bayrog'ini ko'radi va jimgina chiqadi.
    if (waiterIdx !== -1) waiters.splice(waiterIdx, 1)[0].cancel();
  }

  if (activeHolders.length < MAX_CONCURRENT) {
    const next = waiters.shift();
    if (next) next.grant();
  }
  stopRotationTimerIfIdle();
}

export function streamQueueStats(): { active: number; waiting: number } {
  return { active: activeHolders.length, waiting: waiters.length };
}
