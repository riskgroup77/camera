import { useEffect, useState, type FormEvent } from 'react';
import { KeyRound } from 'lucide-react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required, minLength } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AdminUser } from '../../types';

interface FormState {
  name: string;
  login: string;
  email: string;
  role: AdminUser['role'];
}

function toForm(u: AdminUser): FormState {
  return { name: u.name, login: u.login, email: u.email ?? '', role: u.role };
}

export default function EditUserModal({
  user,
  onClose,
  onSave,
}: {
  user: AdminUser | null;
  onClose: () => void;
  onSave: (user: AdminUser) => void;
}) {
  const { token } = useAuth();
  const [form, setForm] = useState<FormState | null>(user ? toForm(user) : null);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>> & { form?: string }>({});
  const [saving, setSaving] = useState(false);

  const [resetting, setResetting] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetDone, setResetDone] = useState(false);
  const [resetSubmitting, setResetSubmitting] = useState(false);

  useEffect(() => {
    if (user) {
      setForm(toForm(user));
      setErrors({});
      setResetting(false);
      setNewPassword('');
      setResetError(null);
      setResetDone(false);
    }
  }, [user]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!user || !form) return;

    const next = {
      name: required(form.name, "F.I.Sh. kiritilishi shart") ?? minLength(form.name, 5),
      login: required(form.login, 'Login kiritilishi shart') ?? minLength(form.login, 3),
      role: form.role ? undefined : 'Rolni tanlang',
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSaving(true);
    try {
      const saved = await api.patch<AdminUser>(
        `/api/users/${user.id}`,
        { name: form.name.trim(), login: form.login.trim(), role: form.role, email: form.email.trim() || null },
        token,
      );
      onSave(saved);
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSaving(false);
    }
  }

  async function handleResetPassword(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    const err = minLength(newPassword, 8);
    if (err) {
      setResetError(err);
      return;
    }

    setResetSubmitting(true);
    setResetError(null);
    try {
      await api.post(`/api/users/${user.id}/reset-password`, { newPassword }, token);
      setResetDone(true);
      setNewPassword('');
    } catch (err) {
      setResetError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
    } finally {
      setResetSubmitting(false);
    }
  }

  return (
    <Modal open={!!user} onClose={onClose} title="Foydalanuvchini tahrirlash" maxWidth="max-w-sm">
      {form && user && (
        <div className="flex flex-col gap-5">
          <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
            {errors.form && (
              <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
                {errors.form}
              </p>
            )}
            <TextField
              label="F.I.Sh."
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              error={errors.name}
            />
            <TextField
              label="Login"
              value={form.login}
              onChange={(e) => set('login', e.target.value)}
              error={errors.login}
              autoComplete="off"
            />
            <TextField
              label="Email (ixtiyoriy)"
              type="email"
              value={form.email}
              onChange={(e) => set('email', e.target.value)}
              autoComplete="off"
            />
            <SelectField
              label="Rol"
              value={form.role}
              onChange={(e) => set('role', e.target.value as AdminUser['role'])}
              error={errors.role}
              options={[
                { value: 'Super Admin', label: 'Super Admin' },
                { value: 'Admin', label: 'Admin' },
              ]}
            />
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={onClose} className="btn-glass">
                Bekor qilish
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {saving ? 'Saqlanmoqda...' : 'Saqlash'}
              </button>
            </div>
          </form>

          <div className="border-t border-white/70 pt-4 dark:border-white/10">
            {!resetting ? (
              <button
                type="button"
                onClick={() => setResetting(true)}
                className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700 transition-colors hover:bg-amber-100 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-400 dark:hover:bg-amber-950/60"
              >
                <KeyRound size={13} />
                Parolni tiklash
              </button>
            ) : resetDone ? (
              <p className="text-center text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                Parol yangilandi — foydalanuvchining barcha eski sessiyalari tugatildi.
              </p>
            ) : (
              <form onSubmit={handleResetPassword} noValidate className="flex flex-col gap-2">
                <p className="text-[11px] text-slate-400 dark:text-slate-500">
                  Foydalanuvchi uchun yangi parol darhol o'rnatiladi (email talab qilinmaydi) —
                  barcha eski sessiyalari avtomatik tugatiladi.
                </p>
                {resetError && (
                  <p className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
                    {resetError}
                  </p>
                )}
                <TextField
                  label="Yangi parol"
                  type="password"
                  placeholder="Kamida 8 belgi"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                />
                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" onClick={() => setResetting(false)} className="btn-glass">
                    Bekor qilish
                  </button>
                  <button
                    type="submit"
                    disabled={resetSubmitting}
                    className="rounded-xl bg-amber-600 px-4 py-2 text-xs font-semibold text-white shadow-btn transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {resetSubmitting ? 'Tiklanmoqda...' : 'Parolni tiklash'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
