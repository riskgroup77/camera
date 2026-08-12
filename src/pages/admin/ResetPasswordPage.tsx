import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Loader2, Lock, ShieldCheck } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { required, minLength } from '../../lib/validation';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<{ password?: string; confirmPassword?: string; form?: string }>({});
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next = {
      password: required(password, 'Yangi parol kiritilishi shart') ?? minLength(password, 8),
      confirmPassword: confirmPassword !== password ? 'Parollar mos kelmadi' : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setLoading(true);
    try {
      await api.post('/api/auth/reset-password', { token, newPassword: password });
      setDone(true);
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <div className="glass w-full max-w-md p-8">
        <div className="mb-6 text-center">
          <h1 className="text-[15px] font-extrabold leading-tight text-slate-900 dark:text-slate-100">
            Farg'ona jamoat salomatligi tibbiyot instituti
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Yangi parol o'rnatish</p>
        </div>

        {!token ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <AlertCircle size={28} className="text-red-500" />
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              Havola yaroqsiz
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Ushbu sahifaga tiklash havolasi orqali o'tish kerak. Login sahifasidan qaytadan
              so'rov yuboring.
            </p>
            <Link to="/admin/login" className="btn-glass mt-2">
              Login sahifasiga qaytish
            </Link>
          </div>
        ) : done ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <CheckCircle2 size={32} className="text-emerald-500" />
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              Parol muvaffaqiyatli o'zgartirildi
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Barcha eski sessiyalar tugatildi — yangi parol bilan qayta kiring.
            </p>
            <Link
              to="/admin/login"
              className="mt-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700"
            >
              Tizimga kirish
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
            {errors.form && (
              <div className="flex items-center gap-2 rounded-xl bg-red-50 dark:bg-red-500/10 px-3 py-2.5 text-xs font-semibold text-red-600 dark:text-red-400">
                <AlertCircle size={14} />
                {errors.form}
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Yangi parol
              </label>
              <div className="relative">
                <Lock
                  size={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
                />
                <input
                  type="password"
                  placeholder="Kamida 8 belgi"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  className="w-full rounded-xl border border-white/80 bg-white/60 py-2.5 pl-9 pr-3 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
                />
              </div>
              {errors.password && (
                <p className="mt-1 text-xs font-medium text-red-500 dark:text-red-400">{errors.password}</p>
              )}
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-400">
                Parolni tasdiqlang
              </label>
              <div className="relative">
                <Lock
                  size={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
                />
                <input
                  type="password"
                  placeholder="Parolni qayta kiriting"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  className="w-full rounded-xl border border-white/80 bg-white/60 py-2.5 pl-9 pr-3 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
                />
              </div>
              {errors.confirmPassword && (
                <p className="mt-1 text-xs font-medium text-red-500 dark:text-red-400">{errors.confirmPassword}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading && <Loader2 size={16} className="animate-spin" />}
              {loading ? 'Saqlanmoqda...' : 'Parolni saqlash'}
            </button>
          </form>
        )}

        <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
          <ShieldCheck size={14} />
          256-bit SSL shifrlash bilan himoyalangan
        </p>
      </div>
    </div>
  );
}
