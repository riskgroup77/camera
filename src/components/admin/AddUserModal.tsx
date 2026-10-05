import { useEffect, useState, type FormEvent } from 'react';
import { Button, ConfirmDialog, Field, Input, Modal, Select } from '../../ui';
import { Notice } from '../settings/kit';
import { required, minLength } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { roleOptionsFor } from '../../lib/permissions';
import { normalizeUzPhone } from '../../lib/notificationsApi';
import type { AdminUser } from '../../types';

interface FormErrors {
  name?: string;
  login?: string;
  role?: string;
  phone?: string;
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
  const { token, role: myRole } = useAuth();
  const roleOptions = roleOptionsFor(myRole);
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState<AdminUser['role'] | ''>('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  // Har ochilishda oyna toza bo'ladi. Ilgari `reset()` faqat muvaffaqiyatli
  // saqlashdan keyin chaqirilardi: "Bekor qilish" bosib qayta ochilganda
  // oldingi login/parol maydonlarda turib qolardi.
  useEffect(() => {
    if (open) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const dirty = Boolean(name || login || email || phone || role || password || confirmPassword);

  /** Yozilgan ma'lumot bir bosishda yo'qolmasin — avval so'raymiz. */
  function requestClose() {
    if (submitting) return;
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    onClose();
  }

  function reset() {
    setName('');
    setLogin('');
    setEmail('');
    setPhone('');
    setRole('');
    setPassword('');
    setConfirmPassword('');
    setErrors({});
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next: FormErrors = {
      name: required(name, 'F.I.Sh. kiritilishi shart') ?? minLength(name, 5),
      login: required(login, 'Login kiritilishi shart') ?? minLength(login, 3),
      role: role ? undefined : 'Rolni tanlang',
      phone: phone.trim() && !normalizeUzPhone(phone) ? "Telefon raqami noto'g'ri (+998 90 123 45 67)" : undefined,
      password: required(password, 'Parol kiritilishi shart') ?? minLength(password, 8),
      confirmPassword: confirmPassword !== password ? 'Parollar mos kelmadi' : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSubmitting(true);
    try {
      const user = await api.post<AdminUser>(
        '/api/users',
        {
          name: name.trim(),
          login: login.trim(),
          password,
          role,
          email: email.trim() || null,
          phone: normalizeUzPhone(phone),
        },
        token,
      );
      onAdd(user);
      reset();
      onClose();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Tarmoq xatosi';
      setErrors({ form: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
    <Modal
      open={open}
      onClose={requestClose}
      title="Yangi foydalanuvchi"
      description="Xodim shu login va parol bilan tizimga kiradi."
      size="md"
      dismissible={!submitting}
      footer={
        <>
          <Button onClick={requestClose} disabled={submitting}>
            Bekor qilish
          </Button>
          <Button type="submit" form="add-user-form" variant="primary" loading={submitting}>
            Qo&apos;shish
          </Button>
        </>
      }
    >
      <form id="add-user-form" onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {/* Server xatosi (masalan "Bu login band") oynaning TEPASIDA —
            ilgari u pastda, uzun forma ostida turardi va uzun ekranda
            ko'rinmay qolardi. */}
        {errors.form && <Notice tone="danger">{errors.form}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="F.I.Sh." required error={errors.name} className="sm:col-span-2">
            <Input placeholder="Alimov Jamshid" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <Field label="Login" required error={errors.login}>
            <Input placeholder="a.alimov" value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Rol" required error={errors.role} hint="Huquqlar matritsasida sozlanadi">
            <Select value={role} onChange={(v) => setRole(v as AdminUser['role'])} options={roleOptions} placeholder="Tanlang" className="sm:w-full" />
          </Field>
          <Field label="Email" hint="Ixtiyoriy">
            <Input type="email" placeholder="a.alimov@fjsti.uz" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Telefon" error={errors.phone} hint="Ixtiyoriy — SMS uchun">
            <Input type="tel" placeholder="+998 90 123 45 67" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Parol" required error={errors.password} hint="Kamida 8 belgi">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </Field>
          <Field label="Parolni tasdiqlang" required error={errors.confirmPassword}>
            <Input
              type="password"
              placeholder="Parolni qayta kiriting"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
        </div>
        <Notice tone="neutral">Parol serverda bcrypt bilan xesh (hash) qilinib saqlanadi — uni hech kim, jumladan administrator ham ko&apos;ra olmaydi.</Notice>
      </form>
    </Modal>
      <ConfirmDialog
        open={confirmDiscard}
        title="Kiritilgan ma'lumotlar o'chib ketadi"
        message="Yangi foydalanuvchi hali saqlanmagan. Oynani yopsangiz, yozilganlar yo'qoladi."
        confirmLabel="Ha, yopilsin"
        cancelLabel="Tahrirga qaytish"
        onCancel={() => setConfirmDiscard(false)}
        onConfirm={() => {
          setConfirmDiscard(false);
          onClose();
        }}
      />
    </>
  );
}
