import { api, ApiError } from './apiClient';
import { config } from './config';

export interface EnrollmentLookupResult {
  recordId: string;
  fullName: string;
  typeLabel: string;
  groupOrPosition: string;
  alreadyEnrolled: boolean;
}

export interface EnrollmentSubmitResult {
  fullName: string;
  biometricsStatus: string;
}

export async function lookupByPassport(passportSeries: string, passportNumber: string): Promise<EnrollmentLookupResult> {
  return api.post<EnrollmentLookupResult>('/api/public/enrollment/lookup', { passportSeries, passportNumber });
}

/**
 * Ko'p burchakdan olingan kadrlar (frames) — birinchisi to'g'ridan qaragan
 * holat bo'lishi kerak (backend uni saqlanadigan rasm sifatida ishlatadi).
 * JWT talab qilinmaydi — /api/public/enrollment/* ochiq (parolsiz) yo'l.
 */
export async function submitEnrollment(
  recordId: string,
  passportSeries: string,
  passportNumber: string,
  frames: Blob[],
): Promise<EnrollmentSubmitResult> {
  const form = new FormData();
  form.append('passportSeries', passportSeries);
  form.append('passportNumber', passportNumber);
  frames.forEach((frame, i) => form.append('photos', frame, `frame-${i}.jpg`));

  const res = await fetch(`${config.apiBaseUrl}/api/public/enrollment/${recordId}/submit`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    let detail = `So'rov muvaffaqiyatsiz tugadi (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* javob JSON emas — standart xabar bilan davom etamiz */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<EnrollmentSubmitResult>;
}
