import { describe, expect, it } from 'vitest';
import { ApiError, TIMEOUT_MESSAGE, TIMEOUT_STATUS } from '../../lib/apiClient';
import { RATE_LIMIT_MESSAGE, authErrorMessage, normalizeAuthErrorText } from './authErrors';

/**
 * QA: kirish/tiklash formalaridagi xato matnlari.
 *
 * Backendda uchala endpoint ham daqiqasiga 5 ta so'rovga cheklangan, lekin
 * slowapi javobida `detail` yo'q — apiClient shuning uchun umumiy
 * "So'rov muvaffaqiyatsiz tugadi (429)" beradi. Foydalanuvchi bundan nima
 * qilish kerakligini bilmaydi.
 */
describe('authErrorMessage', () => {
  it("429 da nima qilish kerakligini o'zbekcha aytadi", () => {
    expect(authErrorMessage(new ApiError(429, "So'rov muvaffaqiyatsiz tugadi (429)"))).toBe(RATE_LIMIT_MESSAGE);
  });

  it('5xx ni serverdagi nosozlik deb ayiradi (parol xatosi emas)', () => {
    const text = authErrorMessage(new ApiError(500, 'Internal Server Error'));
    expect(text).not.toMatch(/Internal/);
    expect(text).toMatch(/Server/);
  });

  it("vaqt tugashida apiClient'ning o'zbekcha matnini saqlaydi", () => {
    expect(authErrorMessage(new ApiError(TIMEOUT_STATUS, TIMEOUT_MESSAGE))).toBe(TIMEOUT_MESSAGE);
  });

  it('401 da serverning "parol noto\'g\'ri" matni o\'zgarmaydi', () => {
    expect(authErrorMessage(new ApiError(401, "Login yoki parol noto'g'ri"))).toBe("Login yoki parol noto'g'ri");
  });

  it('ApiError bo\'lmasa — tarmoq xatosi matni', () => {
    expect(authErrorMessage(new TypeError('Failed to fetch'))).toMatch(/Tarmoq xatosi/);
  });
});

describe('normalizeAuthErrorText', () => {
  it('status yo\'qolgan holatda ham 429 ni matndan tanib oladi', () => {
    expect(normalizeAuthErrorText("So'rov muvaffaqiyatsiz tugadi (429)")).toBe(RATE_LIMIT_MESSAGE);
    expect(normalizeAuthErrorText('Rate limit exceeded: 5 per 1 minute')).toBe(RATE_LIMIT_MESSAGE);
  });

  it("noto'g'ri parol xabarini o'zgartirmaydi", () => {
    expect(normalizeAuthErrorText("Login yoki parol noto'g'ri")).toBe("Login yoki parol noto'g'ri");
  });
});
