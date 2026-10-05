import { ApiError, TIMEOUT_STATUS } from '../../lib/apiClient';

/**
 * Kirish / parolni tiklash formalaridagi xato matni.
 *
 * NEGA KERAK: backendda bu uch endpoint ham IP bo'yicha cheklangan
 * (`@limiter.limit("5/minute")`). Chegaradan o'tilganda slowapi javob
 * tanasiga `{"error": "Rate limit exceeded: 5 per 1 minute"}` yozadi —
 * `detail` maydoni YO'Q. apiClient esa `detail` topilmasa umumiy
 * "So'rov muvaffaqiyatsiz tugadi (429)" matnini beradi. Natijada parolini
 * adashtirgan foydalanuvchi to'rtinchi urinishdan keyin sababi noma'lum
 * raqamli xatoga duch kelardi va nima qilishni bilmay qayta-qayta
 * bosishda davom etardi (bu esa chegarani yana uzaytirardi).
 *
 * Shu bilan birga 5xx va tarmoq xatolari ham foydalanuvchi tilida
 * ayiriladi: "parol noto'g'ri" va "server ishlamayapti" — butunlay
 * boshqa-boshqa harakat talab qiladi.
 */
export function authErrorMessage(err: unknown, fallback = 'Tarmoq xatosi'): string {
  if (err instanceof ApiError) return authErrorFromStatus(err.status, err.message, fallback);
  return fallback;
}

/** `AuthResult.error` faqat satr qaytaradi (status yo'qoladi), shuning uchun
 *  chegara xatosi matndagi "(429)" bo'yicha ham tanib olinadi. */
export function authErrorFromStatus(status: number, message: string, fallback: string): string {
  if (status === 429) return RATE_LIMIT_MESSAGE;
  if (status === TIMEOUT_STATUS) return message; // apiClient allaqachon o'zbekcha bergan
  if (status >= 500) return "Serverda xatolik yuz berdi — birozdan keyin qayta urinib ko'ring";
  return message || fallback;
}

export const RATE_LIMIT_MESSAGE =
  "Juda ko'p urinish bo'ldi. Xavfsizlik uchun kirish vaqtincha cheklandi — bir daqiqadan so'ng qayta urinib ko'ring.";

/** Faqat matn bo'lgan holat uchun (auth.authenticate status'ni yo'qotadi). */
export function normalizeAuthErrorText(text: string): string {
  if (/\(429\)/.test(text) || /rate limit exceeded/i.test(text)) return RATE_LIMIT_MESSAGE;
  if (/\(50\d\)/.test(text)) return "Serverda xatolik yuz berdi — birozdan keyin qayta urinib ko'ring";
  return text;
}
