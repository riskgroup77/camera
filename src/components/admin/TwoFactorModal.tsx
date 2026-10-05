import { useEffect, useState, type FormEvent } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { Badge, Button, CodeText, Field, Input, Modal, useToast } from '../../ui';
import { QrCode } from '../students/EnrollQrCard';
import { Notice } from '../settings/kit';
import { cleanTotpCode, groupSecret, twoFactorApi, type TwoFactorSetup, type TwoFactorStatus } from '../../lib/twoFactorApi';

/**
 * "Ikki bosqichli kirish" — o'z hisobi uchun TOTP'ni yoqish/o'chirish.
 *
 * Holatlar: yuklanmoqda → (o'chiq: "Yoqish" → QR + kod) | (yoqilgan: kod
 * bilan o'chirish). Sir faqat yoqish paytida bir marta ko'rsatiladi —
 * server uni keyin hech qachon qaytarmaydi.
 */
export default function TwoFactorModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStatus(null);
    setSetup(null);
    setCode('');
    setError(null);
    twoFactorApi
      .status()
      .then((s) => !cancelled && setStatus(s))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : 'Holatni olib bo‘lmadi'));
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tarmoq xatosi');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function begin() {
    const result = await run(() => twoFactorApi.begin());
    if (result) {
      setSetup(result);
      setCode('');
    }
  }

  async function submitCode(e: FormEvent) {
    e.preventDefault();
    const cleaned = cleanTotpCode(code);
    if (!cleaned) {
      setError('Ilovadagi 6 xonali kodni kiriting');
      return;
    }
    const enabled = status?.enabled;
    const result = await run(() => (enabled ? twoFactorApi.disable(cleaned) : twoFactorApi.confirm(cleaned)));
    if (!result) return;
    setStatus(result);
    setSetup(null);
    setCode('');
    toast.success(result.enabled ? 'Ikki bosqichli kirish yoqildi' : 'Ikki bosqichli kirish o‘chirildi');
  }

  const codeForm = (label: string, submitLabel: string, danger = false) => (
    <form onSubmit={submitCode} noValidate className="flex flex-col gap-3">
      <Field label={label}>
        <Input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          maxLength={7}
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
            setError(null);
          }}
        />
      </Field>
      <Button type="submit" variant={danger ? 'danger' : 'primary'} loading={busy}>
        {submitLabel}
      </Button>
    </form>
  );

  return (
    <Modal open={open} onClose={onClose} title="Ikki bosqichli kirish" size="sm">
      <div className="flex flex-col gap-3 text-[13px]">
        {error && (
          <p role="alert" className="rounded-control border border-danger/35 bg-danger-soft px-3 py-2 font-medium text-danger">
            {error}
          </p>
        )}

        {!status && !error && <p className="text-muted">Yuklanmoqda…</p>}

        {status?.enabled && (
          <>
            <p className="flex items-center gap-2">
              <Badge tone="success" dot>
                Yoqilgan
              </Badge>
              <span className="text-muted">Kirishda parol va ilovadagi kod so‘raladi.</span>
            </p>
            {codeForm('O‘chirish uchun kod', 'O‘chirish', true)}
          </>
        )}

        {status && !status.enabled && !setup && (
          <>
            <p className="text-muted">
              Parol bilan birga telefondagi ilova (Google Authenticator, Microsoft Authenticator va h.k.) bergan kod so‘raladi.
              Parol sizib chiqsa ham hisobga kirib bo‘lmaydi.
            </p>
            <Button variant="primary" icon={ShieldCheck} loading={busy} onClick={begin}>
              Yoqish
            </Button>
          </>
        )}

        {status && !status.enabled && setup && (
          <>
            <p className="text-muted">1. Ilovada QR-kodni skanerlang.</p>
            <div className="flex justify-center">
              <QrCode value={setup.otpauthUri} className="aspect-square w-48 max-w-full" title="Ikki bosqichli kirish QR-kodi" />
            </div>
            <Notice tone="neutral" icon={KeyRound}>
              Skanerlay olmasangiz, kalitni qo‘lda kiriting:{' '}
              <CodeText className="break-all text-[12px]">{groupSecret(setup.secret)}</CodeText>
            </Notice>
            {codeForm('2. Ilovadagi kod', 'Tasdiqlash')}
          </>
        )}
      </div>
    </Modal>
  );
}
