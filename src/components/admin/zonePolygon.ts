/** Zona ko'pburchagi ustidagi sof matematik yordamchilar (CameraZoneModal).
 *
 *  Alohida fayl — testdan o'tkazish uchun: bu yerdagi xatoni ekranda
 *  ko'rib bo'lmaydi, u faqat AI natijasida (noto'g'ri hududda yuz
 *  qidirish) sezilardi. */

/** Nuqtalar 0-1 oralig'ida normallashtirilgan: 4 kasr xona = 4K kadrda
 *  ~0,4 piksel, ya'ni sichqoncha aniqligidan ham mayda. Ilgari
 *  0.43277310924369745 kabi 17 xonali sonlar saqlanardi — bazada ham,
 *  jurnal solishtirmasida ham shovqin. */
const PRECISION = 4;

export function roundPoint([x, y]: [number, number]): [number, number] {
  const factor = 10 ** PRECISION;
  return [Math.round(x * factor) / factor, Math.round(y * factor) / factor];
}

/** Yumaloqlangandan keyin oldingi nuqta bilan ustma-ust tushgan bosish
 *  hisobga olinmaydi: ikki marta bosilib qolgan joy ko'pburchakka
 *  "nol uzunlikdagi tomon" qo'shardi. */
export function appendPoint(points: [number, number][], next: [number, number]): [number, number][] {
  const rounded = roundPoint(next);
  const last = points[points.length - 1];
  if (last && last[0] === rounded[0] && last[1] === rounded[1]) return points;
  return [...points, rounded];
}

/** Ko'pburchak yuzi (shoelace). Belgisi yo'nalishga bog'liq — modul olamiz. */
export function polygonArea(points: [number, number][]): number {
  if (points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

function segmentsCross(a: [number, number], b: [number, number], c: [number, number], d: [number, number]): boolean {
  const cross = (p: [number, number], q: [number, number], r: [number, number]) =>
    (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = cross(c, d, a);
  const d2 = cross(c, d, b);
  const d3 = cross(a, b, c);
  const d4 = cross(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

/** Ko'pburchak o'z-o'zini kesib o'tadimi ("kapalak" shakl).
 *
 *  Bunday shaklda "ichkarisi" tushunchasi yo'q: backend'dagi nuqta-ichida
 *  tekshiruvi kutilmagan natija beradi va operator chizgan joyda odam
 *  turgani aniqlanmay qolishi mumkin. Backend faqat nuqtalar sonini
 *  tekshiradi, shuning uchun bu yerda ushlaymiz. */
export function isSelfIntersecting(points: [number, number][]): boolean {
  const n = points.length;
  if (n < 4) return false;
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 1; j < n; j += 1) {
      // Qo'shni (umumiy uchli) tomonlar tekshirilmaydi.
      if (i === j || (i + 1) % n === j || (j + 1) % n === i) continue;
      if (segmentsCross(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) return true;
    }
  }
  return false;
}

/** Saqlashdan oldingi tekshiruv. `null` — hammasi joyida. */
export function validatePolygon(points: [number, number][]): string | null {
  if (points.length === 0) return null;
  if (points.length < 3) return "Zona kamida 3 ta nuqtadan iborat bo'lishi kerak";
  // Kesishish tekshiruvi OLDIN: simmetrik "kapalak" shaklning shoelace
  // yuzi ham 0 chiqadi, lekin sabab bitta chiziq emas — kesishish.
  if (isSelfIntersecting(points)) {
    return "Chiziqlar bir-birini kesib o'tmoqda — zona chegarasi noaniq. Nuqtalarni ketma-ket, aylana bo'ylab belgilang";
  }
  if (polygonArea(points) < 0.0001) {
    return "Nuqtalar bitta chiziqda — zonaning ichi yo'q. Uchinchi nuqtani chetroqqa qo'ying";
  }
  return null;
}
