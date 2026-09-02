import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, api, setUnauthorizedHandler } from './apiClient';
import { isBackendConfigured } from './config';

export type Role = 'super-admin' | 'admin';

interface AuthState {
  role: Role | null;
  userName: string | null;
  /** Backend integratsiyasidan keyin JWT/session token shu yerda saqlanadi. Demo rejimida doim null. */
  token: string | null;
}

interface AuthContextValue extends AuthState {
  authenticate: (role: Role, login: string, password: string) => Promise<AuthResult>;
  login: (role: Role, userName: string, token?: string | null) => void;
  logout: () => void;
}

export type AuthResult =
  | { ok: true; userName: string; role: Role; token: string | null }
  | { ok: false; error: string };

const STORAGE_KEY = 'camera-auth';

// Demo hisob ma'lumotlari — backend ulanmaganda ishlatiladigan zaxira rejim.
export const DEMO_CREDENTIALS: Record<Role, { login: string; password: string }> = {
  'super-admin': { login: 'admin', password: 'admin123' },
  admin: { login: 'operator', password: 'operator123' },
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readAuth(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { token: null, ...JSON.parse(raw) } as AuthState;
  } catch {
    /* ignore */
  }
  return { role: null, userName: null, token: null };
}

interface LoginResponse {
  token: string;
  role: Role;
  userName: string;
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
      return { ok: true, userName: res.userName, role: res.role, token: res.token };
    } catch (err) {
      if (err instanceof ApiError) return { ok: false, error: err.message };
      return { ok: false, error: "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" };
    }
  }

  // Real tarmoq so'rovini simulyatsiya qilish uchun kichik kechikish.
  await new Promise((resolve) => setTimeout(resolve, 400));

  const creds = DEMO_CREDENTIALS[role];
  if (login.trim() === creds.login && password.trim() === creds.password) {
    return { ok: true, userName: login.trim(), role, token: null };
  }
  return { ok: false, error: "Login yoki parol noto'g'ri" };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(readAuth);

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

  function login(role: Role, userName: string, token: string | null = null) {
    const next: AuthState = { role, userName, token };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  function logout() {
    const outgoingToken = state.token;
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
    <AuthContext.Provider value={{ ...state, authenticate, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
