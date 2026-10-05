import { config } from './config';
import { clearReportToken, reportToken } from './reportLock';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  isForm?: boolean;
  /** Eskirgan so'rovni bekor qilish (filtr o'zgarganda, sahifadan chiqilganda). */
  signal?: AbortSignal;
  responseType?: 'json' | 'blob';
  /** 0 — chegara yo'q (uzun yuklashlar). Berilmasa — standart. */
  timeoutMs?: number;
}

/** FastAPI/pydantic 422 javoblari inglizcha ("String should have at least 8
 *  characters") — ular o'zbekcha interfeysga to'g'ridan-to'g'ri chiqib
 *  ketardi. Bu yerda maydon nomi bilan tushunarli xabar yasaymiz; noma'lum
 *  holatda esa umumiy o'zbekcha matn beriladi. */
function validationMessage(items: { msg?: string; loc?: unknown[] }[], status: number): string {
  const fields = items
    .map((item) => {
      const loc = Array.isArray(item.loc) ? item.loc : [];
      const name = [...loc].reverse().find((part) => typeof part === 'string' && part !== 'body');
      return typeof name === 'string' ? name : null;
    })
    .filter((name): name is string => Boolean(name));
  const unique = [...new Set(fields)];
  if (unique.length > 0) {
    return `Kiritilgan ma'lumot noto'g'ri: ${unique.join(', ')}. Maydonlarni tekshirib qayta urinib ko'ring`;
  }
  return `Kiritilgan ma'lumot noto'g'ri (${status}). Maydonlarni tekshirib qayta urinib ko'ring`;
}

export interface CallOptions {
  signal?: AbortSignal;
}

/**
 * Sessiya yaroqsiz bo'lganda (401) chaqiriladigan ishlovchi — auth.tsx
 * uni o'rnatadi (setUnauthorizedHandler), shu orqali apiClient React'ga
 * bog'lanib qolmaydi (aylanma import bo'lmaydi).
 *
 * Bunisiz: token muddati tugagach har bir so'rov jimgina 401 qaytarardi,
 * saqlangan (endi yaroqsiz) token localStorage'da qolib ketardi, UI esa
 * bo'sh panellar va konsol to'la xato bilan qotib turardi — foydalanuvchi
 * o'zi taxmin qilib qayta kirmaguncha. Endi sessiya darhol tozalanadi,
 * RequireAuth esa admin sahifalarini login'ga yo'naltiradi, ochiq
 * sahifadagi panellar "Tizimga kiring" holatiga tushadi.
 */
type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

/**
 * Joriy sessiya tokenini beruvchi — auth.tsx uni o'rnatadi
 * (setAuthTokenGetter), setUnauthorizedHandler bilan bir xil sababga
 * ko'ra: apiClient React'ga bog'lanib qolmasin.
 *
 * Nega kerak bo'ldi: token har bir chaqiruvga QO'LDA uzatilardi
 * (api.get(path, token)). Bu admin sahifalarida ishlardi, chunki ular
 * doim token uzatgan. Monitoring devori esa /api/public/* ni ochiq deb
 * bilib, hech qachon uzatmagan — va o'sha endpointlar himoyalanishi
 * bilan har biri 401 qaytardi, sahifa esa xatoni ko'rsatmasdan bo'sh
 * ro'yxat chizdi: "hech qanday kamera ulanmagan".
 *
 * Buni oltita chaqiruv joyiga qo'lda token qo'shib ham tuzatsa
 * bo'lardi, lekin keyingi yangi chaqiruv yana o'shani unutardi —
 * server shartnomasi o'zgarganda mijozning HAMMA joyini eslab qolish
 * kerak bo'lgan yechim ishonchli emas. Endi token bitta joydan
 * qo'shiladi; aniq uzatilgan token esa baribir ustun turadi (login
 * so'rovi kabi maxsus holatlar uchun).
 */
type TokenGetter = () => string | null;
let getAuthToken: TokenGetter | null = null;

export function setAuthTokenGetter(getter: TokenGetter | null): void {
  getAuthToken = getter;
}

/** Joriy login tokeni — JSON bo'lmagan so'rovlar uchun (masalan WebRTC SDP). */
export function getAccessToken(): string | null {
  return getAuthToken?.() ?? null;
}

/** API manzilining boshi (dev'da boshqa port bo'lishi mumkin). */
export function apiUrl(path: string): string {
  return `${config.apiBaseUrl}${path}`;
}

/**
 * So'rov qancha kutishi mumkin.
 *
 * Bunisiz: server javob bermay qotib qolsa (qayta ishga tushayotgan
 * backend, uzilgan VPN, "yarim ochiq" TCP), `fetch` hech qachon
 * tugamasdi — foydalanuvchi esa aylanayotgan spinnerga soatlab qarab
 * o'tirardi, chunki na xato, na "Qayta urinish" tugmasi paydo bo'lardi.
 * Endi belgilangan vaqtdan keyin oddiy xato: ekranda sabab va qayta
 * urinish tugmasi.
 */
export const REQUEST_TIMEOUT_MS = 30_000;
/** Fayl (Excel/PDF) tayyorlash uzoqroq — lekin abadiy emas. */
export const BLOB_TIMEOUT_MS = 120_000;

export const TIMEOUT_MESSAGE = "Server javob bermadi (vaqt tugadi) — qayta urinib ko'ring";
/** Vaqt tugaganda status: HTTP javobi umuman bo'lmagani uchun 0. */
export const TIMEOUT_STATUS = 0;

async function request<T>(
  path: string,
  { method = 'GET', body, token, isForm, signal, responseType = 'json', timeoutMs }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const authToken = token ?? getAuthToken?.() ?? null;
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  // Hisobotlar paroli bilan olingan kalit (lib/reportLock.ts) — faqat hisobot so'rovlariga.
  if (/^\/api\/(hisobot|kpi|reports|situation\/analytics\/(summary|heatmap|people))/.test(path)) {
    const unlock = reportToken();
    if (unlock) headers['X-Report-Token'] = unlock;
  }
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';

  // Chaqiruvchining bekor qilishi (filtr o'zgardi) va vaqt chegarasi —
  // ikkalasi bitta signalga yig'iladi, lekin ularni FARQLASH kerak:
  // bekor qilish jim o'tadi, vaqt tugashi esa xato bo'lib ko'rinadi.
  const limit = timeoutMs ?? (responseType === 'blob' ? BLOB_TIMEOUT_MS : REQUEST_TIMEOUT_MS);
  const controller = new AbortController();
  let timedOut = false;
  const timer = limit > 0 ? setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, limit) : undefined;
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener('abort', onOuterAbort);
  if (signal?.aborted) controller.abort();

  let res: Response;
  try {
    res = await fetch(`${config.apiBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (timedOut && !signal?.aborted) throw new ApiError(TIMEOUT_STATUS, TIMEOUT_MESSAGE);
    // Tarmoq uzilishi: brauzer "Failed to fetch" (inglizcha) beradi — foydalanuvchiga tushunarli matn.
    if (!signal?.aborted && err instanceof TypeError) {
      throw new ApiError(0, "Serverga ulanib bo'lmadi — internet aloqasini tekshiring");
    }
    throw err;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal?.removeEventListener('abort', onOuterAbort);
  }

  if (!res.ok) {
    // Faqat token YUBORILGAN so'rovda: ya'ni sessiya yaroqli bo'lishi
    // kutilgan edi, lekin server rad etdi => sessiya tugagan. Login
    // so'rovining 401'i (noto'g'ri parol) bunga kirmaydi — aks holda
    // login sahifasi o'zini cheksiz "chiqish"ga yuborardi.
    if (res.status === 401 && authToken) onUnauthorized?.();
    // Administrator, 2FA hali yoqilmagan — sozlash oynasi ochiladi (ForcedTwoFactor).
    if (res.status === 403 && res.headers.get('X-2FA-Required') === '1' && typeof window !== 'undefined') {
      window.dispatchEvent(new Event(TWO_FACTOR_REQUIRED_EVENT));
    }
    // Hisobot kaliti yaroqsiz (boshqa foydalanuvchiniki, muddati o'tgan yoki
    // server kaliti almashgan) — kalit o'chiriladi va parol oynasi qaytadi.
    if (res.status === 403 && res.headers.get('X-Report-Locked') === '1' && typeof window !== 'undefined') {
      clearReportToken();
      window.dispatchEvent(new Event(REPORT_LOCKED_EVENT));
    }

    let detail = `So'rov muvaffaqiyatsiz tugadi (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
      else if (Array.isArray(data.detail)) detail = validationMessage(data.detail, res.status);
      // slowapi 429'ni `{"error": ...}` ko'rinishida qaytaradi — `detail` yo'q,
      // shuning uchun foydalanuvchi quruq "(429)" ko'rardi.
      else if (res.status === 429) detail = "Juda ko'p urinish. Bir daqiqadan so'ng qayta urinib ko'ring";
    } catch {
      /* javob JSON emas — standart xabar bilan davom etamiz */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  if (responseType === 'blob') return (await res.blob()) as T;
  return res.json() as Promise<T>;
}

/** Server "2FA majburiy" deganda chiqariladigan hodisa nomi. */
export const TWO_FACTOR_REQUIRED_EVENT = 'camera:2fa-required';
/** Server hisobot kalitini qabul qilmadi — ReportGate parolni qayta so'raydi. */
export const REPORT_LOCKED_EVENT = 'camera:report-locked';

export const api = {
  get: <T>(path: string, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'GET', token, signal: opts.signal }),
  post: <T>(path: string, body: unknown, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'POST', body, token, signal: opts.signal }),
  patch: <T>(path: string, body: unknown, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'PATCH', body, token, signal: opts.signal }),
  put: <T>(path: string, body: unknown, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'PUT', body, token, signal: opts.signal }),
  del: (path: string, token?: string | null, opts: CallOptions = {}) =>
    request<void>(path, { method: 'DELETE', token, signal: opts.signal }),
  postForm: <T>(path: string, form: FormData, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'POST', body: form, token, isForm: true, signal: opts.signal }),
  putForm: <T>(path: string, form: FormData, token?: string | null, opts: CallOptions = {}) =>
    request<T>(path, { method: 'PUT', body: form, token, isForm: true, signal: opts.signal }),
  /** Fayl (Excel) — xato bo'lsa JSON'dagi `detail` bilan ApiError. */
  blob: (path: string, token?: string | null, opts: CallOptions = {}) =>
    request<Blob>(path, { method: 'GET', token, signal: opts.signal, responseType: 'blob' }),
};

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') usp.set(key, String(value));
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

/** Walk every page of a paginated list endpoint (max pageSize 500 on API).
 *
 * `maxRows` — eksport uchun yuqori chegara: 4300 ta hodisani brauzer
 * xotirasiga yig'ish ham, uni CSV ga yozish ham cheksiz bo'lmasligi kerak.
 * Chegaraga yetganda so'rovlar to'xtaydi va ro'yxat shu yerda kesiladi —
 * chaqiruvchi `rows.length >= maxRows` bo'yicha buni foydalanuvchiga aytadi. */
export async function fetchAllPages<T>(
  path: string,
  token: string | null | undefined,
  params: Record<string, string | number | undefined | null> = {},
  pageSize = 500,
  maxRows = Number.POSITIVE_INFINITY,
): Promise<T[]> {
  const all: T[] = [];
  let page = 1;
  let totalPages = 1;
  do {
    const qs = buildQuery({ ...params, page, pageSize });
    const res = await api.get<Page<T>>(`${path}${qs}`, token);
    all.push(...res.items);
    totalPages = res.totalPages;
    page += 1;
  } while (page <= totalPages && all.length < maxRows);
  return all.length > maxRows ? all.slice(0, maxRows) : all;
}
