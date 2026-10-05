import { api } from './apiClient';

/** Ikki bosqichli kirish (TOTP) — camera-api/app/routers/auth.py /api/auth/2fa/*. */
export interface TwoFactorStatus {
  enabled: boolean;
  confirmedAt: string | null;
}

export interface TwoFactorSetup {
  /** otpauth://totp/... — QR shu satrdan chiziladi. */
  otpauthUri: string;
  /** QR'ni skanerlay olmaganlar uchun qo'lda kiritiladigan kalit. */
  secret: string;
}

export const twoFactorApi = {
  status: () => api.get<TwoFactorStatus>('/api/auth/2fa'),
  begin: () => api.post<TwoFactorSetup>('/api/auth/2fa/boshlash', undefined),
  confirm: (code: string) => api.post<TwoFactorStatus>('/api/auth/2fa/tasdiqlash', { code }),
  disable: (code: string) => api.post<TwoFactorStatus>('/api/auth/2fa/ochirish', { code }),
};

/** Kalitni 4 belgidan guruhlab ko'rsatadi — qo'lda ko'chirish oson bo'lsin. */
export function groupSecret(secret: string): string {
  return secret.replace(/(.{4})/g, '$1 ').trim();
}

/** "123 456" yoki "123-456" ham qabul qilinadi; aks holda null. */
export function cleanTotpCode(code: string): string | null {
  const cleaned = code.replace(/[\s-]+/g, '');
  return /^\d{6}$/.test(cleaned) ? cleaned : null;
}
