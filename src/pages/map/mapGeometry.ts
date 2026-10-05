/** Xarita geometriyasi — sof funksiyalar (DOM'siz, alohida test qilinadi).
 *
 * Burchak kelishuvi: 0° — rejada yuqoriga, soat mili bo'yicha ortadi
 * (kompas kabi). Ekran koordinatasida y pastga o'sgani uchun yo'nalish
 * vektori (sin a, -cos a). */

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

/** Istalgan burchakni 0..359 butun gradusga keltiradi. */
export function normalizeAngle(deg: number): number {
  const rounded = Math.round(deg) % 360;
  return rounded < 0 ? rounded + 360 : rounded;
}

/** Rasmni konteynerga nisbatini saqlab sig'diradi (object-fit: contain). */
export function fitSize(container: Size, image: Size): Size {
  if (container.width <= 0 || container.height <= 0 || image.width <= 0 || image.height <= 0) {
    return { width: 0, height: 0 };
  }
  const scale = Math.min(container.width / image.width, container.height / image.height);
  return { width: image.width * scale, height: image.height * scale };
}

/** Ekrandagi nuqta (clientX/Y) → reja ichidagi nisbiy koordinata (0..1).
 *  Chetdan tashqaridagi nuqta chetga yopishadi — marker rejadan chiqib ketmaydi. */
export function toNormalized(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }): Point {
  if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
  return {
    x: clamp01((clientX - rect.left) / rect.width),
    y: clamp01((clientY - rect.top) / rect.height),
  };
}

/** Nisbiy koordinata → ko'rsatilayotgan reja pikseli. */
export function toPixels(point: Point, size: Size): Point {
  return { x: point.x * size.width, y: point.y * size.height };
}

/** Markazdan `deg` yo'nalishda `distance` uzoqlikdagi nuqta. */
export function polar(center: Point, deg: number, distance: number): Point {
  const rad = (deg * Math.PI) / 180;
  return { x: center.x + Math.sin(rad) * distance, y: center.y - Math.cos(rad) * distance };
}

/** Markazdan nuqtaga qaragan burchak (0..359) — aylantirish tutqichi uchun. */
export function angleBetween(center: Point, target: Point): number {
  const dx = target.x - center.x;
  const dy = target.y - center.y;
  if (dx === 0 && dy === 0) return 0;
  return normalizeAngle((Math.atan2(dx, -dy) * 180) / Math.PI);
}

const r2 = (n: number) => Math.round(n * 100) / 100;

/** Ko'rish konusi (sektor) uchun SVG path. fov ≥ 360 — to'liq doira
 *  (360° kamera, masalan fisheye). */
export function conePath(center: Point, angle: number, fov: number, radius: number): string {
  if (radius <= 0) return '';
  if (fov >= 360) {
    const top = r2(center.y - radius);
    const bottom = r2(center.y + radius);
    return `M ${r2(center.x)} ${top} A ${r2(radius)} ${r2(radius)} 0 1 1 ${r2(center.x)} ${bottom} A ${r2(radius)} ${r2(radius)} 0 1 1 ${r2(center.x)} ${top} Z`;
  }
  const half = Math.max(1, fov) / 2;
  const start = polar(center, angle - half, radius);
  const end = polar(center, angle + half, radius);
  const largeArc = fov > 180 ? 1 : 0;
  return `M ${r2(center.x)} ${r2(center.y)} L ${r2(start.x)} ${r2(start.y)} A ${r2(radius)} ${r2(radius)} 0 ${largeArc} 1 ${r2(end.x)} ${r2(end.y)} Z`;
}

/** Konus uzunligi: reja o'lchamiga mos, lekin juda kichik ekranda ham ko'rinadigan. */
export function coneRadius(size: Size): number {
  return Math.max(28, Math.min(size.width, size.height) * 0.09);
}
