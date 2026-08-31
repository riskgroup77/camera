/** HLS oqimlar navbati — bir vaqtda max 8 ta parallel ulanish. Faqat
 * 'scroll' rejimidagi kartalar shu navbatdan foydalanadi (devor rejimlari
 * — wall-4/9/16 — navbatni butunlay chetlab o'tadi, chunki foydalanuvchi
 * aynan shu N ta kamerani bir vaqtda ko'rishni tanlagan va joy hech qachon
 * bo'shamaydi: LiveVideoPlayer joy(slot)ni faqat komponent unmount
 * bo'lganda (masalan scroll rejimida ekrandan chiqib ketganda) bo'shatadi
 * — devor rejimida kartalar hech qachon unmount bo'lmaydi, shuning uchun
 * MAX_CONCURRENT'dan oshgan kartalar abadiy "yuklanmoqda" holatida qolib
 * ketardi.
 */
const MAX_CONCURRENT = 8;
let active = 0;
const waiters: Array<() => void> = [];

export function acquireStreamSlot(): Promise<void> {
  if (active < MAX_CONCURRENT) {
    active += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    waiters.push(() => {
      active += 1;
      resolve();
    });
  });
}

export function releaseStreamSlot(): void {
  active = Math.max(0, active - 1);
  const next = waiters.shift();
  if (next) next();
}

export function streamQueueStats(): { active: number; waiting: number } {
  return { active, waiting: waiters.length };
}
