import { config } from './config';

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

async function request<T>(path: string, { method = 'GET', body, token, isForm }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const authToken = token ?? getAuthToken?.() ?? null;
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${config.apiBaseUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });

  if (!res.ok) {
    // Faqat token YUBORILGAN so'rovda: ya'ni sessiya yaroqli bo'lishi
    // kutilgan edi, lekin server rad etdi => sessiya tugagan. Login
    // so'rovining 401'i (noto'g'ri parol) bunga kirmaydi — aks holda
    // login sahifasi o'zini cheksiz "chiqish"ga yuborardi.
    if (res.status === 401 && authToken) onUnauthorized?.();

    let detail = `So'rov muvaffaqiyatsiz tugadi (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg?: string }) => d.msg).join(', ');
    } catch {
      /* javob JSON emas — standart xabar bilan davom etamiz */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, token?: string | null) => request<T>(path, { method: 'GET', token }),
  post: <T>(path: string, body: unknown, token?: string | null) => request<T>(path, { method: 'POST', body, token }),
  patch: <T>(path: string, body: unknown, token?: string | null) => request<T>(path, { method: 'PATCH', body, token }),
  del: (path: string, token?: string | null) => request<void>(path, { method: 'DELETE', token }),
  postForm: <T>(path: string, form: FormData, token?: string | null) =>
    request<T>(path, { method: 'POST', body: form, token, isForm: true }),
};

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

/** Walk every page of a paginated list endpoint (max pageSize 500 on API). */
export async function fetchAllPages<T>(
  path: string,
  token: string | null | undefined,
  params: Record<string, string | number | undefined | null> = {},
  pageSize = 500,
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
  } while (page <= totalPages);
  return all;
}
