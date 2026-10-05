import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Eye, EyeOff, Link2Off, Lock } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { required, minLength } from '../../lib/validation';
import { authErrorMessage } from '../../components/admin/authErrors';
import { Button, ButtonLink, CodeText, Field, IconButton, Input, MicroLabel, Readout, StatusLamp } from '../../ui';
import { formNumber } from '../../components/public/formNumber';

/** Tiklash havolasining amal qilish muddati — backenddagi
 *  RESET_TOKEN_TTL_MINUTES bilan bir xil. Foydalanuvchiga "nega
 *  ishlamadi"ni tushuntirish uchun ekranda ko'rsatiladi. */
const RESET_LINK_TTL_MINUTES = 30;

/** Blankning yuqori qismi — uchala holatda ham bir xil: nima
 *  to'ldirilyapti, blank raqami, amal muddati va joriy holat SO'Z bilan.
 *  Raqam holatdan hisoblanadi, vaqtdan emas. */
function FormHead({
  title,
  state,
  status,
  statusLabel,
}: {
  title: string;
  /** Blank raqamiga ta'sir qiladigan holat (maxfiy token EMAS). */
  state: string;
  status: 'ok' | 'warn' | 'alert' | 'idle';
  statusLabel: string;
}) {
  return (
    <>
      <div className="flex items-start gap-3 border-b border-border pb-2.5">
        <div className="min-w-0 flex-1">
          <MicroLabel>Blank</MicroLabel>
          <h1 className="mt-0.5 text-[16px] font-semibold tracking-tight text-fg">{title}</h1>
        </div>
        <CodeText className="shrink-0 pt-0.5 text-[11px] font-semibold text-fg">
          {formNumber({ kind: 'parol', parts: [state] })}
        </CodeText>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-b border-border py-2.5 sm:grid-cols-3">
        <Readout label="Amal" value="Parol tiklash" />
        <Readout label="Havola muddati" value={`${RESET_LINK_TTL_MINUTES} daq`} title="Tiklash havolasi shu muddatda va bir marta ishlaydi" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <MicroLabel>Holat</MicroLabel>
          <StatusLamp status={status} label={statusLabel} />
        </div>
      </div>
    </>
  );
}

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<{ password?: string; confirmPassword?: string; form?: string }>({});
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  // Server "havola yaroqsiz yoki muddati tugagan" desa, formani qayta
  // to'ldirishning ma'nosi yo'q — bu holatda aynan havolasiz kelgandagi
  // ekran ko'rsatiladi, unda esa "yangi so'rov yuborish" yo'li bor.
  const [linkDead, setLinkDead] = useState(false);

  /** Tasdiq maydoni: birinchi yuborishdan KEYIN har bosishda qayta
   *  tekshiriladi. Ilgari xato faqat "Saqlash"da hisoblanardi — odam
   *  parolni to'g'rilab bo'lsa ham "Parollar mos kelmadi" qizarib turardi
   *  va u yana xato qilgan deb o'ylardi. */
  function liveErrors(nextPassword: string, nextConfirm: string) {
    if (!submitted) return;
    setErrors((prev) => ({
      ...prev,
      password: required(nextPassword, 'Yangi parol kiritilishi shart') ?? minLength(nextPassword, 8),
      confirmPassword: nextConfirm && nextConfirm !== nextPassword ? 'Parollar mos kelmadi' : undefined,
    }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
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
      // 400 — token yo'q, ishlatilgan yoki muddati tugagan (routers/auth.py).
      if (err instanceof ApiError && err.status === 400) {
        setLinkDead(true);
        return;
      }
      setErrors({ form: authErrorMessage(err) });
    } finally {
      setLoading(false);
    }
  }

  if (!token || linkDead) {
    return (
      <div>
        <FormHead
          title={linkDead ? 'Havola muddati tugagan' : 'Havola yaroqsiz'}
          state={linkDead ? 'havola-tugagan' : 'havola-yoq'}
          status="alert"
          statusLabel={linkDead ? 'Muddati tugagan' : 'Yaroqsiz'}
        />
        <div className="flex items-start gap-3 pt-3.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-danger/35 bg-danger-soft text-danger">
            <Link2Off size={16} aria-hidden="true" />
          </span>
          <p className="min-w-0 text-[13px] leading-relaxed text-muted">
            {linkDead
              ? `Tiklash havolasi faqat ${RESET_LINK_TTL_MINUTES} daqiqa va bir marta ishlaydi. Bu havola allaqachon ishlatilgan yoki muddati tugagan — kirish sahifasidagi “Parolni unutdingizmi?” orqali yangisini so'rang.`
              : "Bu sahifaga elektron xatdagi tiklash havolasi orqali o'tiladi. Kirish sahifasidan qaytadan so'rov yuboring."}
          </p>
        </div>
        <ButtonLink to="/kirish" className="mt-4" fullWidth>
          Kirish sahifasiga qaytish
        </ButtonLink>
      </div>
    );
  }

  if (done) {
    return (
      <div>
        <FormHead title="Parol o'zgartirildi" state="bajarildi" status="ok" statusLabel="Bajarildi" />
        <div className="flex items-start gap-3 pt-3.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-success/35 bg-success-soft text-success">
            <CheckCircle2 size={16} aria-hidden="true" />
          </span>
          <p className="min-w-0 text-[13px] leading-relaxed text-muted">
            Barcha eski sessiyalar tugatildi — yangi parol bilan qayta kiring.
          </p>
        </div>
        <ButtonLink to="/kirish" variant="primary" className="mt-4" fullWidth>
          Tizimga kirish
        </ButtonLink>
      </div>
    );
  }

  return (
    <div>
      <FormHead
        title="Yangi parol o'rnatish"
        state="forma"
        status={loading ? 'warn' : errors.form ? 'alert' : 'idle'}
        statusLabel={loading ? 'Saqlanmoqda' : errors.form ? 'Rad etildi' : "To'ldirilmoqda"}
      />
      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        Kamida 8 belgidan iborat yangi parol kiriting. Saqlangach barcha eski sessiyalar tugatiladi.
      </p>

      <form onSubmit={handleSubmit} noValidate className="mt-4 flex flex-col gap-3.5">
        {errors.form && (
          <div role="alert" className="flex items-start gap-2 rounded-control border border-danger/35 bg-danger-soft px-3 py-2.5 text-[13px] font-medium text-danger">
            <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0">{errors.form}</span>
          </div>
        )}

        <Field label="Yangi parol" error={errors.password}>
          <Input
            icon={Lock}
            size="lg"
            type={showPassword ? 'text' : 'password'}
            placeholder="Kamida 8 belgi"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              liveErrors(e.target.value, confirmPassword);
            }}
            autoComplete="new-password"
            autoFocus
            trailing={
              // Parolni ikki marta ko'rmasdan yozish — eng ko'p uchraydigan
              // "Parollar mos kelmadi" sababi. Ko'rsatish tugmasi kirish
              // sahifasidagi bilan bir xil.
              <IconButton
                icon={showPassword ? EyeOff : Eye}
                label={showPassword ? 'Parolni yashirish' : "Parolni ko'rsatish"}
                size="sm"
                pressed={showPassword}
                onClick={() => setShowPassword((v) => !v)}
              />
            }
          />
        </Field>

        <Field label="Parolni tasdiqlang" error={errors.confirmPassword}>
          <Input
            icon={Lock}
            size="lg"
            type={showPassword ? 'text' : 'password'}
            placeholder="Parolni qayta kiriting"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              liveErrors(password, e.target.value);
            }}
            autoComplete="new-password"
          />
        </Field>

        <Button type="submit" variant="primary" size="lg" fullWidth loading={loading}>
          {loading ? 'Saqlanmoqda…' : 'Parolni saqlash'}
        </Button>
      </form>
    </div>
  );
}
