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

/** Tiriklik tekshiruvining bosqichlari — server bilan AYNAN bir xil
 *  tartibda. Tartib muhim: /submit kadrlarni shu ketma-ketlikda kutadi
 *  va har birini tegishli burilishga solishtiradi. */
export const LIVENESS_STEPS = ['front', 'left', 'right'] as const;
export type LivenessStep = (typeof LIVENESS_STEPS)[number];

export interface PoseCheckResult {
  faceFound: boolean;
  faces: number;
  direction: LivenessStep | null;
  ratio: number | null;
  closeEnough: boolean;
  ok: boolean;
  hint: string;
}

/** Jonli yo'naltirish: hozirgi kadrda yuz qaysi tomonga qaragan.
 *
 *  Javob faqat ekrandagi ko'rsatma uchun — yakuniy hukm serverda,
 *  submitEnrollment ichida chiqariladi. Mijoz aytgan "ok" ga ishonilmaydi. */
export async function checkPose(expected: LivenessStep, frame: Blob): Promise<PoseCheckResult> {
  const form = new FormData();
  form.append('expected', expected);
  form.append('photo', frame, 'probe.jpg');

  const res = await fetch(`${config.apiBaseUrl}/api/public/enrollment/pose-check`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new ApiError(res.status, `Tekshiruv bajarilmadi (${res.status})`);
  return res.json() as Promise<PoseCheckResult>;
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
 * Tiriklik tekshiruvining uchta kadri: to'g'riga qaragan, chapga va
 * o'ngga burilgan — AYNAN shu tartibda.
 *
 * Server har bir kadrni tegishli burilishga solishtiradi va faqat
 * hammasi mos kelganda yuzni saqlaydi. Kadrlar bir xil odamniki
 * ekanligi ham alohida tekshiriladi, so'ng ularning o'rtacha vektori
 * olinadi — bu kamera odamni keyinchalik qaysi tomondan ko'rishidan
 * qat'i nazar tanishini aniqroq qiladi.
 *
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
