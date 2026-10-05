/** Videodevor kodlari — har kameraga qisqa, barqaror "xizmat raqami".
 *
 * Operator ekranida kameraning nomi uzun va takrorlanuvchi bo'ladi
 * ("Kirish eshigi 2"), shuning uchun har katakda monoshrift kod turadi:
 * `CAM-084`. Kod kameraning TO'LIQ ro'yxatdagi (filtrsiz, id bo'yicha
 * tartiblangan) o'rnidan olinadi, ya'ni filtr yoki setka o'zgarganda
 * o'zgarmaydi — operator kodni eslab qolishi mumkin.
 *
 * Ikkinchi kod — joy: `B2·Q3` (bino · qavat). U kameraning o'z
 * ma'lumotidan olinadi, o'ylab topilgan raqam emas: bino nomidagi
 * birinchi son (yoki birinchi harf) va qavat raqami.
 *
 * Bu yerda faqat sof funksiyalar — holat ham, so'rov ham yo'q. */

export const UNKNOWN_CAMERA_CODE = 'CAM-???';

const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

/** Ro'yxatdagi o'rindan kod: 1 -> CAM-001, 84 -> CAM-084, 1234 -> CAM-1234. */
export function formatCameraCode(position: number): string {
  if (!Number.isFinite(position) || position < 1) return UNKNOWN_CAMERA_CODE;
  return `CAM-${String(Math.trunc(position)).padStart(3, '0')}`;
}

/** Barcha kameralar uchun id -> kod jadvali (id bo'yicha tabiiy tartib). */
export function buildCameraCodes(cameras: readonly { id: string }[]): Map<string, string> {
  const ids = [...new Set(cameras.map((camera) => camera.id))].sort((a, b) => collator.compare(a, b));
  return new Map(ids.map((id, index) => [id, formatCameraCode(index + 1)]));
}

/** Jadvaldan kod; kamera topilmasa — "noma'lum" kodi. */
export function cameraCode(codes: ReadonlyMap<string, string>, id: string | null | undefined): string {
  if (!id) return UNKNOWN_CAMERA_CODE;
  return codes.get(id) ?? UNKNOWN_CAMERA_CODE;
}

/** Bino belgisi: "2-Bino" -> B2, "Asosiy" -> BA, bo'sh -> ''. */
function buildingToken(building: string | null | undefined): string {
  const value = (building ?? '').trim();
  if (!value) return '';
  const digits = value.match(/\d+/);
  if (digits) return `B${Number(digits[0])}`;
  const letter = value.match(/\p{L}/u);
  return letter ? `B${letter[0].toLocaleUpperCase('en')}` : '';
}

/** Joy kodi: `B2·Q3`. Ma'lumot bo'lmasa bo'sh satr (hech narsa o'ylab topilmaydi). */
export function cameraPlaceCode(camera: { building?: string | null; floor?: number | null } | null | undefined): string {
  if (!camera) return '';
  const parts: string[] = [];
  const building = buildingToken(camera.building);
  if (building) parts.push(building);
  if (typeof camera.floor === 'number' && Number.isFinite(camera.floor)) parts.push(`Q${Math.trunc(camera.floor)}`);
  return parts.join('·');
}
