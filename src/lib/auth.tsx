import { createContext, useContext, useEffect, useState, type ReactNode, useRef } from 'react';
import { ApiError, api, setAuthTokenGetter, setUnauthorizedHandler } from './apiClient';
import { isBackendConfigured } from './config';
import { clearReportToken } from './reportLock';

export type Role = 'super-admin' | 'admin' | 'kamera-masuli';

interface AuthState {
  role: Role | null;
  userName: string | null;
  /** Backend integratsiyasidan keyin JWT/session token shu yerda saqlanadi. Demo rejimida doim null. */
  token: string | null;
}

interface AuthContextValue extends AuthState {
  authenticate: (role: Role, login: string, password: string) => Promise<AuthResult>;
  /** Ikkinchi qadam: parol bilan olingan chaqiruv + ilovadagi 6 xonali kod. */
  verifyTwoFactor: (challenge: string, code: string) => Promise<AuthResult>;
  login: (role: Role, userName: string, token?: string | null) => void;
  logout: () => void;
  /** Administrator, 2FA hali yoqilmagan — server faqat sozlashni ochadi. */
  twoFactorRequired: boolean;
}

export type AuthResult =
  | { ok: true; userName: string; role: Role; token: string | null }
  | { ok: false; error: string }
  /** Parol to'g'ri, lekin hisobda ikki bosqichli kirish yoqilgan — hali
   *  sessiya YO'Q, faqat 5 daqiqalik bir martalik chaqiruv. */
  | { ok: false; twoFactor: true; challenge: string };

export const STORAGE_KEY = 'camera-auth';

const ROLES: readonly Role[] = ['super-admin', 'admin', 'kamera-masuli'];

function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value);
}

/** Boshqa oynada (tab) sessiya o'zgargani bilinishi uchun eng kam vaqt —
 *  `storage` hodisasi darhol keladi, bu esa faqat fokusdagi tekshiruv. */
export const SESSION_RECHECK_MS = 60_000;

/** Demo rejimda kirish mumkin bo'lgan rollar. Kamera mas'uli bu yerda
 * ATAYLAB yo'q: u faqat haqiqiy backend bilan ishlaydigan rol. */
export type DemoRole = Extract<Role, 'super-admin' | 'admin'>;

// Demo hisob ma'lumotlari — backend ulanmaganda ishlatiladigan zaxira rejim.
export const DEMO_CREDENTIALS: Record<DemoRole, { login: string; password: string }> = {
  'super-admin': { login: 'admin', password: 'admin123' },
  admin: { login: 'operator', password: 'operator123' },
};

const AuthContext = createContext<AuthContextValue | null>(null);

const EMPTY: AuthState = { role: null, userName: null, token: null };

/** Saqlangan sessiyani O'QIYDI VA TEKSHIRADI.
 *
 *  Ilgari `JSON.parse` natijasi qanday bo'lsa shundayligicha holatga
 *  tushardi: localStorage'ga qo'lda (yoki eski versiyadan qolgan)
 *  `{"role":"buxgalter"}` yozilsa, `ROLE_COLUMN[role]` undefined bo'lib
 *  menyu bo'sh, sahifa esa oq qolardi — chiqib qayta kirmaguncha. Endi
 *  noma'lum rol umuman sessiya emas: foydalanuvchi kirish sahifasiga
 *  tushadi. */
function parseAuth(raw: string | null): AuthState {
  if (!raw) return EMPTY;
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (!data || typeof data !== 'object' || !isRole(data.role)) return EMPTY;
    return {
      role: data.role,
      userName: typeof data.userName === 'string' ? data.userName : null,
      token: typeof data.token === 'string' ? data.token : null,
    };
  } catch {
    return EMPTY;
  }
}

function readAuth(): AuthState {
  try {
    return parseAuth(localStorage.getItem(STORAGE_KEY));
  } catch {
    return EMPTY;
  }
}

function sameSession(a: AuthState, b: AuthState): boolean {
  return a.role === b.role && a.userName === b.userName && a.token === b.token;
}

interface LoginResponse {
  token: string | null;
  role: Role | null;
  userName: string | null;
  twoFactorRequired?: boolean;
  challenge?: string | null;
}

function loginResult(res: LoginResponse): AuthResult {
  if (res.twoFactorRequired && res.challenge) return { ok: false, twoFactor: true, challenge: res.challenge };
  if (!res.token || !isRole(res.role)) return { ok: false, error: 'Serverdan kutilmagan javob keldi' };
  return { ok: true, userName: res.userName ?? '', role: res.role, token: res.token };
}

function authError(err: unknown): AuthResult {
  if (err instanceof ApiError) return { ok: false, error: err.message };
  return { ok: false, error: "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" };
}

/**
 * Login/parolni tekshiradi. Backend ulangan bo'lsa (VITE_API_BASE_URL
 * sozlangan) haqiqiy POST /api/auth/login so'rovini yuboradi — rol
 * backend tomonidan hisobning o'zidan aniqlanadi, login ekranidagi
 * "Super Admin / Admin" tugmasidan EMAS (bu tugma faqat qaysi demo
 * login/parolni ko'rsatishni tanlash uchun UX yordamchisi, xavfsizlik
 * chegarasi emas). Backend ulanmagan bo'lsa, demo hisoblar bilan ishlaydi.
 */
async function authenticate(role: Role, login: string, password: string): Promise<AuthResult> {
  if (isBackendConfigured) {
    try {
      const res = await api.post<LoginResponse>('/api/auth/login', { login: login.trim(), password: password.trim() });
      return loginResult(res);
    } catch (err) {
      return authError(err);
    }
  }

  // Real tarmoq so'rovini simulyatsiya qilish uchun kichik kechikish.
  await new Promise((resolve) => setTimeout(resolve, 400));

  const creds = role === 'kamera-masuli' ? undefined : DEMO_CREDENTIALS[role];
  if (creds && login.trim() === creds.login && password.trim() === creds.password) {
    return { ok: true, userName: login.trim(), role, token: null };
  }
  return { ok: false, error: "Login yoki parol noto'g'ri" };
}

async function verifyTwoFactor(challenge: string, code: string): Promise<AuthResult> {
  try {
    const res = await api.post<LoginResponse>('/api/auth/2fa/kirish', { challenge, code: code.replace(/[\s-]+/g, '') });
    return loginResult(res);
  } catch (err) {
    return authError(err);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(readAuth);

  // apiClient har bir so'rovga tokenni shu yerdan oladi — izohi
  // apiClient.ts'dagi setAuthTokenGetter'da.
  //
  // ref orqali, state orqali emas: getter apiClient ichida saqlanadi va
  // uni har render'da qayta o'rnatish (yoki eski qiymatni yopib qolish)
  // token yangilangach eskisini yuborishga olib kelardi. ref esa doim
  // oxirgi qiymatni ko'rsatadi.
  const tokenRef = useRef(state.token);
  tokenRef.current = state.token;

  // Ro'yxatdan o'tkazish RENDER paytida, useEffect'da EMAS.
  //
  // React bola komponentlarning effektlarini otanikidan OLDIN ishga
  // tushiradi. Bu getter effektda o'rnatilganda, MonitoringPage o'z
  // ma'lumotini allaqachon so'rab bo'lgan bo'lardi — token'siz. Natija:
  // sahifa birinchi ochilishida 401 va "Kameralarni yuklab bo'lmadi",
  // keyingi har qanday so'rov esa muammosiz. Aynan shu holat
  // production'da kuzatildi.
  //
  // Render paytida chaqirish bu yerda xavfsiz: getter faqat ref o'qiydi,
  // holatni o'zgartirmaydi va bir necha marta chaqirilishi hech narsani
  // buzmaydi.
  setAuthTokenGetter(() => tokenRef.current);

  // Effekt ichida ham qayta o'rnatiladi: StrictMode (dev) effektlarni
  // "o'chirib-yoqib" sinaydi — faqat tozalash bo'lsa, getter null bo'lib
  // qolardi va keyingi render'gacha so'rovlar tokensiz ketardi (401).
  useEffect(() => {
    setAuthTokenGetter(() => tokenRef.current);
    return () => setAuthTokenGetter(null);
  }, []);

  // Token muddati tugagach (server 401 qaytarganda) sessiyani darhol
  // tozalaymiz — apiClient.ts'dagi setUnauthorizedHandler izohiga qarang.
  // Bu yerda serverga logout so'rovi YUBORILMAYDI: token allaqachon
  // yaroqsiz, va 401 to'lqini paytida har biriga bittadan so'rov yuborish
  // faqat shovqin bo'lardi.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setState((current) => {
        if (!current.token && !current.role) return current; // allaqachon tozalangan
        localStorage.removeItem(STORAGE_KEY);
        return { role: null, userName: null, token: null };
      });
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  // BOSHQA OYNA (tab) bilan bitta sessiya.
  //
  // Bir brauzerda ikki tab ochiq bo'lishi — bu ilovada odatiy hol (devor
  // ekrani + ish tabi). Ilgari har tab o'z nusxasini ushlab turardi:
  // birida "Chiqish" bosilsa, ikkinchisi ilovani ko'rsatishda davom
  // etardi va har so'rovda 401 olardi (yoki teskarisi — boshqa hisob
  // bilan kirilgach, eski tab hali ham eski rol menyusini chizardi).
  // `storage` hodisasi faqat BOSHQA tablarda ishlaydi — aynan kerakli joy.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== STORAGE_KEY) return;
      // key === null — localStorage butunlay tozalangan.
      const next = event.key === null ? readAuth() : parseAuth(event.newValue);
      setState((current) => (sameSession(current, next) ? current : next));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // ROL SERVERDA O'ZGARSA — MENYU O'ZGARSIN.
  //
  // Rol endi har so'rovda bazadan o'qiladi (app/dependencies.py), lekin
  // mijoz uni kirish paytida olib 12 soat (JWT TTL) saqlab turardi:
  // lavozimidan olingan odam o'z ekranida "Super Admin" yozuvini va to'liq
  // menyuni ko'rib yurardi — bosgan har tugmasi 403 bilan qaytsa ham.
  // GET /api/auth/me — bitta yengil so'rov: ochilganda va oyna yana fokusga
  // kelganda (lekin daqiqada bir martadan ko'p emas — so'rov to'lqini
  // bo'lmasin). 401 bo'lsa apiClient sessiyani o'zi tozalaydi.
  const lastCheck = useRef(0);
  const [twoFactorRequired, setTwoFactorRequired] = useState(false);
  useEffect(() => {
    if (!isBackendConfigured || !state.token) return;
    let cancelled = false;
    const token = state.token;

    const check = () => {
      const now = Date.now();
      if (now - lastCheck.current < SESSION_RECHECK_MS) return;
      lastCheck.current = now;
      api
        .get<{ role: Role; userName: string; twoFactorRequired?: boolean }>('/api/auth/me', token)
        .then((session) => {
          if (cancelled) return;
          setTwoFactorRequired(Boolean(session.twoFactorRequired));
          if (!isRole(session.role)) return;
          setState((current) => {
            if (current.token !== token) return current; // sessiya allaqachon almashgan
            if (current.role === session.role && current.userName === session.userName) return current;
            const next: AuthState = { role: session.role, userName: session.userName, token };
            try {
              localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
            } catch {
              /* saqlab bo'lmadi — xotirada baribir to'g'ri */
            }
            return next;
          });
        })
        .catch(() => {
          /* tarmoq xatosi — eski rol bilan davom etamiz, 401 bo'lsa
             setUnauthorizedHandler allaqachon tozalagan */
        });
    };

    lastCheck.current = 0;
    check();
    const onFocus = () => {
      if (document.visibilityState !== 'hidden') check();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [state.token]);

  function login(role: Role, userName: string, token: string | null = null) {
    const next: AuthState = { role, userName, token };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  function logout() {
    const outgoingToken = state.token;
    setTwoFactorRequired(false);
    // Hisobot kaliti shu foydalanuvchiniki — keyingi kirgan odamga qolmasin.
    clearReportToken();
    const next: AuthState = { role: null, userName: null, token: null };
    setState(next);
    localStorage.removeItem(STORAGE_KEY);

    // Real server-side bekor qilish — mahalliy holatni tozalashni kutib
    // o'tirmaydi (UI darhol javob beradi), lekin token endi backendda ham
    // haqiqatan yaroqsiz bo'ladi (POST /api/auth/logout — blocklist).
    if (isBackendConfigured && outgoingToken) {
      api.post('/api/auth/logout', undefined, outgoingToken).catch(() => {
        /* tarmoq xatosi — token baribir muddati tugaguncha real hisoblanadi */
      });
    }
  }

  return (
    <AuthContext.Provider value={{ ...state, authenticate, verifyTwoFactor, login, logout, twoFactorRequired }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
