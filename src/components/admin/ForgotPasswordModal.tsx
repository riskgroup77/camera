import { useState, type FormEvent } from 'react';
import { CheckCircle2, Loader2, Mail } from 'lucide-react';
import Modal from '../Modal';
import { TextField } from '../FormField';
import { required } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { isBackendConfigured } from '../../lib/config';

export default function ForgotPasswordModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [login, setLogin] = useState('');
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  function handleClose() {
    setLogin('');
    setError(undefined);
    setLoading(false);
    setSent(false);
    onClose();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err = required(login, 'Login kiritilishi shart');
    if (err) {
      setError(err);
      return;
    }
    setError(undefined);
    setLoading(true);

    if (isBackendConfigured) {
      try {
        await api.post('/api/auth/forgot-password', { login: login.trim() });
        setSent(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
      } finally {
        setLoading(false);
      }
      return;
    }

    // Demo rejim — backend ulanmagan.
    await new Promise((resolve) => setTimeout(resolve, 900));
    setLoading(false);
    setSent(true);
  }

  return (
    <Modal open={open} onClose={handleClose} title="Parolni tiklash" maxWidth="max-w-sm">
      {sent ? (
        <div className="flex flex-col items-center gap-3 py-2 text-center">
          <CheckCircle2 size={32} className="text-emerald-500" />
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            So'rov qabul qilindi
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Agar bunday hisob mavjud bo'lsa va unga elektron pochta biriktirilgan bo'lsa, parolni
            tiklash havolasi shu manzilga yuborildi. Email topilmasa, tizim administratoriga
            murojaat qiling.
          </p>
          <button onClick={handleClose} className="btn-glass mt-2">
            Yopish
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Hisobingizga bog'langan loginni kiriting — agar unga elektron pochta manzili
            biriktirilgan bo'lsa, tiklash havolasi shu manzilga yuboriladi.
          </p>
          <div className="relative">
            <Mail
              size={16}
              className="pointer-events-none absolute left-3 top-[34px] text-slate-400 dark:text-slate-500"
            />
            <TextField
              label="Login"
              placeholder="admin"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              error={error}
              className="pl-9"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={handleClose} className="btn-glass">
              Bekor qilish
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              {loading ? 'Yuborilmoqda...' : 'Yuborish'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
