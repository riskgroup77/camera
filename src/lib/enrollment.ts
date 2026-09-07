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

export interface EnrollmentFaculty {
  id: string;
  name: string;
}

export interface EnrollmentRegisterInput {
  fullName: string;
  type: 'talaba' | 'xodim';
  groupOrPosition: string;
  facultyId?: string;
  pinfl?: string;
  passportSeries?: string;
  passportNumber?: string;
}

/** Shaxsni aniqlash uchun kiritilgan ma'lumot.
 *
 *  Ikki yo'l bor va ular bir-birini almashtiradi: JSHSHIR (institut
 *  kadrlar ro'yxatidagi asosiy raqam) yoki pasport seriyasi va raqami.
 *  Ommaviy import qilingan xodimlarda faqat JSHSHIR bor. */
export type EnrollmentIdentity =
  | { kind: 'pinfl'; pinfl: string }
  | { kind: 'passport'; passportSeries: string; passportNumber: string };

function identityPayload(identity: EnrollmentIdentity) {
  return identity.kind === 'pinfl'
    ? { pinfl: identity.pinfl }
    : { passportSeries: identity.passportSeries, passportNumber: identity.passportNumber };
}

export async function lookupPerson(identity: EnrollmentIdentity): Promise<EnrollmentLookupResult> {
  return api.post<EnrollmentLookupResult>('/api/public/enrollment/lookup', identityPayload(identity));
}

export async function listEnrollmentFaculties(): Promise<EnrollmentFaculty[]> {
  return api.get<EnrollmentFaculty[]>('/api/public/enrollment/faculties');
}

/** Tizimda yozuvi yo'q odam o'zini ro'yxatdan o'tkazadi. Javob lookup
 *  bilan bir xil shaklda — shuning uchun chaqiruvchi keyingi qadamda
 *  ikkisini ajratib o'tirmaydi. */
export async function registerSelf(input: EnrollmentRegisterInput): Promise<EnrollmentLookupResult> {
  return api.post<EnrollmentLookupResult>('/api/public/enrollment/register', input);
}

/**
 * Yuz rasmlari. Bitta yuklangan rasm ham yetarli — backend birinchisini
 * saqlanadigan profil rasmi sifatida ishlatadi, bir nechtasi berilsa
 * ularning o'rtachasini oladi va bir xil odam ekanligini tekshiradi.
 * JWT talab qilinmaydi — /api/public/enrollment/* ochiq (parolsiz) yo'l.
 */
export async function submitEnrollment(
  recordId: string,
  identity: EnrollmentIdentity,
  frames: Blob[],
): Promise<EnrollmentSubmitResult> {
  const form = new FormData();
  // Server /lookup dagi bilan AYNAN bir xil tekshiruvni qayta bajaradi —
  // shuning uchun bu yerda ham o'sha ma'lumot yuboriladi.
  Object.entries(identityPayload(identity)).forEach(([key, value]) => {
    if (value) form.append(key, value);
  });
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
