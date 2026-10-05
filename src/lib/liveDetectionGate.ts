/** Bir vaqtning o'zida faqat bitta kamera live-detection poll qiladi —
 * fon AI sweep'lari bilan inference navbatini bo'lishmaslik uchun. */
const MAX_SLOTS = 1;

let active = new Set<string>();

export function tryAcquireLiveDetection(cameraId: string): boolean {
  if (active.has(cameraId)) return true;
  if (active.size >= MAX_SLOTS) return false;
  active.add(cameraId);
  return true;
}

export function releaseLiveDetection(cameraId: string): void {
  active.delete(cameraId);
}
