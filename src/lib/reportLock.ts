/**
 * Hisobotlar paroli (camera-api/app/routers/report_lock.py).
 *
 * Parol serverda tekshiriladi; to'g'ri bo'lsa server shu foydalanuvchi uchun
 * vaqtinchalik kalit beradi. Kalit brauzer sessiyasida (sessionStorage)
 * saqlanadi — oyna yopilsa yana so'raladi — va apiClient uni har so'rovga
 * X-Report-Token sarlavhasi bilan qo'shadi.
 */

const STORAGE_KEY = 'hisobot-kalit';

interface StoredToken {
  token: string;
  expiresAt: string;
}

function read(): StoredToken | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as StoredToken;
    if (!value.token || new Date(value.expiresAt).getTime() <= Date.now()) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function reportToken(): string | null {
  if (typeof window === 'undefined') return null;
  return read()?.token ?? null;
}

export function saveReportToken(token: string, expiresAt: string): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ token, expiresAt }));
  } catch {
    /* sessionStorage yopiq — har safar so'raladi */
  }
}

export function clearReportToken(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* e'tiborsiz */
  }
}
