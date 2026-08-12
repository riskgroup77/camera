import { useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required, minLength } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AdminUser } from '../../types';

interface FormErrors {
  name?: string;
  login?: string;
  role?: string;
  password?: string;
  confirmPassword?: string;
  form?: string;
}

export default function AddUserModal({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (user: AdminUser) => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<AdminUser['role'] | ''>('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setName('');
    setLogin('');
    setEmail('');
    setRole('');
    setPassword('');
    setConfirmPassword('');
    setErrors({});
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next: FormErrors = {
      name: required(name, "F.I.Sh. kiritilishi shart") ?? minLength(name, 5),
      login: required(login, 'Login kiritilishi shart') ?? minLength(login, 3),
      role: role ? undefined : 'Rolni tanlang',
      password: required(password, 'Parol kiritilishi shart') ?? minLength(password, 8),
      confirmPassword:
        confirmPassword !== password ? 'Parollar mos kelmadi' : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSubmitting(true);
    try {
      const user = await api.post<AdminUser>(
        '/api/users',
        { name: name.trim(), login: login.trim(), password, role, email: email.trim() || null },
        token,
      );
      onAdd(user);
      reset();
      onClose();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi";
      setErrors({ form: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Yangi foydalanuvchi qo'shish" maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}
        <TextField
          label="F.I.Sh."
          placeholder="Alimov Jamshid"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <TextField
          label="Login"
          placeholder="a.alimov"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
          error={errors.login}
          autoComplete="off"
        />
        <TextField
          label="Email (ixtiyoriy)"
          type="email"
          placeholder="a.alimov@fjsti.uz"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="off"
        />
        <SelectField
          label="Rol"
          placeholder="Tanlang"
          value={role}
          onChange={(e) => setRole(e.target.value as AdminUser['role'])}
          error={errors.role}
          options={[
            { value: 'Super Admin', label: 'Super Admin' },
            { value: 'Admin', label: 'Admin' },
          ]}
        />
        <TextField
          label="Parol"
          type="password"
          placeholder="Kamida 8 belgi"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
          autoComplete="new-password"
        />
        <TextField
          label="Parolni tasdiqlang"
          type="password"
          placeholder="Parolni qayta kiriting"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          error={errors.confirmPassword}
          autoComplete="new-password"
        />
        <p className="text-[11px] text-slate-400 dark:text-slate-500">
          Rolning huquqlarini "Huquqlar matritsasi" bo'limida sozlash mumkin. Parol backendda
          bcrypt bilan xesh (hash) qilinib saqlanadi.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {submitting ? 'Qo\'shilmoqda...' : "Qo'shish"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
