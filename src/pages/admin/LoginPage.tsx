import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, Eye, EyeOff, Loader2, Lock, ShieldCheck, User } from 'lucide-react';
import { useAuth, DEMO_CREDENTIALS, type Role } from '../../lib/auth';
import ForgotPasswordModal from '../../components/admin/ForgotPasswordModal';

interface FieldErrors {
  login?: string;
  password?: string;
  form?: string;
}

function validateLogin(login: string): string | undefined {
  if (!login.trim()) return 'Login kiritilishi shart';
  if (login.trim().length < 3) return 'Login kamida 3 belgidan iborat bo\'lishi kerak';
}

function validatePassword(password: string): string | undefined {
  if (!password) return 'Parol kiritilishi shart';
  if (password.length < 6) return 'Parol kamida 6 belgidan iborat bo\'lishi kerak';
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const auth = useAuth();
  const [role, setRole] = useState<Role>('super-admin');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [touched, setTouched] = useState<{ login?: boolean; password?: boolean }>({});
  const [loading, setLoading] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);

  function handleBlur(field: 'login' | 'password') {
    setTouched((t) => ({ ...t, [field]: true }));
    setErrors((e) => ({
      ...e,
      login: field === 'login' ? validateLogin(login) : e.login,
      password: field === 'password' ? validatePassword(password) : e.password,
    }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const loginError = validateLogin(login);
    const passwordError = validatePassword(password);
    setTouched({ login: true, password: true });

    if (loginError || passwordError) {
      setErrors({ login: loginError, password: passwordError });
      return;
    }

    setErrors({});
    setLoading(true);

    const result = await auth.authenticate(role, login, password);
    if (result.ok) {
      // Haqiqiy rol backend javobidan olinadi (yoki demo rejimida tekshirilgan
      // hisobdan) — yuqoridagi tugma faqat qaysi demo login/parolni ko'rsatish
      // uchun, xavfsizlik chegarasi emas.
      auth.login(result.role, result.userName, result.token);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from.startsWith('/admin') ? from : '/admin', { replace: true });
      return;
    }
    setLoading(false);
    setErrors({ form: result.error });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <div className="glass w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <h1 className="text-[15px] font-extrabold leading-tight text-slate-900 dark:text-slate-100">
            Farg'ona jamoat salomatligi tibbiyot instituti
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Situatsion Markaz — Boshqaruv Paneliga Kirish
          </p>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-2 rounded-xl border border-white/80 dark:border-white/10 bg-white/40 p-1">
          <button
            type="button"
            onClick={() => setRole('super-admin')}
            className={`rounded-lg py-2 text-sm font-semibold transition-colors ${
              role === 'super-admin'
                ? 'bg-white text-indigo-600 shadow-btn dark:bg-white/10 dark:text-indigo-400'
                : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            Super Admin
          </button>
          <button
            type="button"
            onClick={() => setRole('admin')}
            className={`rounded-lg py-2 text-sm font-semibold transition-colors ${
              role === 'admin'
                ? 'bg-white text-indigo-600 shadow-btn dark:bg-white/10 dark:text-indigo-400'
                : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            Admin
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
          {errors.form && (
            <div className="flex items-center gap-2 rounded-xl bg-red-50 dark:bg-red-500/10 px-3 py-2.5 text-xs font-semibold text-red-600 dark:text-red-400">
              <AlertCircle size={14} />
              {errors.form}
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-400">
              Login
            </label>
            <div className="relative">
              <User
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
              />
              <input
                type="text"
                placeholder="admin"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                onBlur={() => handleBlur('login')}
                aria-invalid={touched.login && !!errors.login}
                className={`w-full rounded-xl border bg-white/60 dark:bg-white/5 py-2.5 pl-9 pr-3 text-sm text-slate-900 dark:text-slate-100 outline-none transition-colors placeholder:text-slate-400 dark:text-slate-500 ${
                  touched.login && errors.login
                    ? 'border-red-300 focus:border-red-400'
                    : 'border-white/80 dark:border-white/10 focus:border-indigo-300'
                }`}
              />
            </div>
            {touched.login && errors.login && (
              <p className="mt-1 text-xs font-medium text-red-500 dark:text-red-400">{errors.login}</p>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-400">
              Parol
            </label>
            <div className="relative">
              <Lock
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
              />
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => handleBlur('password')}
                aria-invalid={touched.password && !!errors.password}
                className={`w-full rounded-xl border bg-white/60 dark:bg-white/5 py-2.5 pl-9 pr-9 text-sm text-slate-900 dark:text-slate-100 outline-none transition-colors placeholder:text-slate-400 dark:text-slate-500 ${
                  touched.password && errors.password
                    ? 'border-red-300 focus:border-red-400'
                    : 'border-white/80 dark:border-white/10 focus:border-indigo-300'
                }`}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {touched.password && errors.password && (
              <p className="mt-1 text-xs font-medium text-red-500 dark:text-red-400">{errors.password}</p>
            )}
          </div>

          <div className="flex items-center justify-between text-xs">
            <label className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="rounded border-slate-300 dark:border-white/10"
              />
              Eslab qolish
            </label>
            <button
              type="button"
              onClick={() => setForgotOpen(true)}
              className="font-semibold text-indigo-600 hover:underline dark:text-indigo-400"
            >
              Parolni unutdingizmi?
            </button>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {loading && <Loader2 size={16} className="animate-spin" />}
            {loading ? 'Tekshirilmoqda...' : 'Tizimga kirish'}
          </button>

          <p className="text-center text-[11px] text-slate-400 dark:text-slate-500">
            Demo: {DEMO_CREDENTIALS[role].login} / {DEMO_CREDENTIALS[role].password}
          </p>
        </form>

        <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
          <ShieldCheck size={14} />
          256-bit SSL shifrlash bilan himoyalangan
        </p>
      </div>

      <ForgotPasswordModal open={forgotOpen} onClose={() => setForgotOpen(false)} />
    </div>
  );
}
