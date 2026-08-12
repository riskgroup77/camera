export function required(value: string, message = "Bu maydon to'ldirilishi shart"): string | undefined {
  if (!value.trim()) return message;
}

export function minLength(value: string, min: number, message?: string): string | undefined {
  if (value.trim().length < min) return message ?? `Kamida ${min} belgi kiritilishi kerak`;
}

export function ipAddress(value: string): string | undefined {
  const parts = value.trim().split('.');
  if (parts.length !== 4 || parts.some((p) => !/^\d{1,3}$/.test(p) || Number(p) > 255)) {
    return "IP manzil noto'g'ri formatda (masalan: 192.168.1.10)";
  }
}

export function numberRange(value: string, min: number, max: number, message?: string): string | undefined {
  const n = Number(value);
  if (value.trim() === '' || Number.isNaN(n)) return 'Raqam kiritilishi shart';
  if (n < min || n > max) return message ?? `${min} dan ${max} gacha bo'lgan qiymat kiriting`;
}
