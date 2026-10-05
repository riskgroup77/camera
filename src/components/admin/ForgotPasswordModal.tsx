import { useState, type FormEvent } from 'react';
import { CheckCircle2, User } from 'lucide-react';
import { Button, Field, Input, Modal } from '../../ui';
import { required } from '../../lib/validation';
import { api } from '../../lib/apiClient';
import { authErrorMessage } from './authErrors';
import { isBackendConfigured } from '../../lib/config';

export default function ForgotPasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
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
        // 429 (daqiqasiga 5 ta so'rov) umumiy "(429)" matni bilan kelardi —
        // authErrors.ts izohiga qarang.
        setError(authErrorMessage(err));
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

  if (sent) {
    return (
      <Modal open={open} onClose={handleClose} size="sm" ariaLabel="Parolni tiklash" footer={<Button onClick={handleClose} data-autofocus>Yopish</Button>}>
        <div className="flex flex-col items-center gap-3 pb-1 pt-4 text-center" role="status">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-success-soft text-success">
            <CheckCircle2 size={24} aria-hidden="true" />
          </span>
          <p className="text-base font-semibold text-fg">So&apos;rov qabul qilindi</p>
          <p className="text-[13px] leading-relaxed text-muted">
            Agar bunday hisob mavjud bo&apos;lsa va unga elektron pochta biriktirilgan bo&apos;lsa, parolni tiklash havolasi shu manzilga
            yuborildi. Havola 30 daqiqa va faqat bir marta amal qiladi. Email topilmasa, spam papkasini tekshiring yoki tizim
            administratoriga murojaat qiling.
          </p>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Parolni tiklash"
      description="Loginni kiriting — havola pochtangizga yuboriladi."
      size="sm"
      dismissible={!loading}
      footer={
        <>
          <Button onClick={handleClose} disabled={loading}>
            Bekor qilish
          </Button>
          <Button type="submit" form="forgot-password-form" variant="primary" loading={loading}>
            {loading ? 'Yuborilmoqda...' : 'Yuborish'}
          </Button>
        </>
      }
    >
      <form id="forgot-password-form" onSubmit={handleSubmit} noValidate className="flex flex-col gap-4 pb-1">
        <Field label="Login" error={error}>
          <Input
            icon={User}
            placeholder="admin"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            data-autofocus
          />
        </Field>
      </form>
    </Modal>
  );
}
