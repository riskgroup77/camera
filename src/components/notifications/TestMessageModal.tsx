import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Send } from 'lucide-react';
import { Button, Field, Input, Modal, Select, Textarea } from '../../ui';
import { Notice } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import {
  notificationsApi,
  validateRecipient,
  type NotificationChannel,
  type NotificationStatus,
  type NotificationTestResult,
} from '../../lib/notificationsApi';

const CHANNEL_OPTIONS = [
  { value: 'telegram', label: 'Telegram' },
  { value: 'sms', label: 'SMS (Eskiz)' },
];

/** "Sinov xabari": sozlamalar to'g'riligini darhol tekshirish — natija
 *  (yoki Telegram/Eskiz qaytargan xato) shu oynada ko'rinadi. */
export default function TestMessageModal({
  open,
  status,
  onClose,
  onSent,
}: {
  open: boolean;
  status: NotificationStatus | null;
  onClose: () => void;
  onSent: () => void;
}) {
  const { token } = useAuth();
  const [channel, setChannel] = useState<NotificationChannel>('telegram');
  const [recipient, setRecipient] = useState('');
  const [text, setText] = useState('');
  // Maydon xatosi (noto'g'ri raqam) va yuborish xatosi (tarmoq/server)
  // ALOHIDA: ilgari ikkalasi ham "Telefon raqami" maydoni tagida chiqardi
  // va "Tarmoq xatosi" raqam noto'g'ridek ko'rinardi.
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [result, setResult] = useState<NotificationTestResult | null>(null);
  const [sending, setSending] = useState(false);

  // `status` har yangilanishda YANGI obyekt bo'ladi (useApiResource). Effekt
  // unga bog'liq bo'lganda, oyna ochiq turib holat fonda yangilansa,
  // foydalanuvchi yozgan raqam va matn jimgina o'chib ketardi. Shuning
  // uchun faqat `open` ga bog'liq, `status` esa ref orqali o'qiladi.
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    if (!open) return;
    const s = statusRef.current;
    setChannel(s && !s.telegramConfigured && s.smsConfigured ? 'sms' : 'telegram');
    setRecipient('');
    setText('');
    setFieldError(null);
    setSendError(null);
    setResult(null);
  }, [open]);

  /** Kiritish o'zgarsa oldingi natija/xato eskiradi — ular boshqa
   *  qabul qiluvchiga tegishli bo'lib qoladi, shuning uchun tozalanadi. */
  function clearOutcome() {
    setResult(null);
    setSendError(null);
    setFieldError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const [clean, err] = validateRecipient(channel, recipient);
    if (!clean) {
      setFieldError(err ?? 'Qabul qiluvchini kiriting');
      return;
    }
    setFieldError(null);
    setSendError(null);
    setResult(null);
    setSending(true);
    try {
      const res = await notificationsApi.sendTest({ channel, recipient: clean, text: text.trim() || null }, token);
      setResult(res);
      onSent();
    } catch (err2) {
      setSendError(err2 instanceof ApiError ? err2.message : 'Tarmoq xatosi');
    } finally {
      setSending(false);
    }
  }

  const channelReady = channel === 'telegram' ? status?.telegramConfigured : status?.smsConfigured;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Sinov xabari"
      description="Natija jurnalga ham yoziladi."
      size="md"
      dismissible={!sending}
      footer={
        <>
          <Button onClick={onClose} disabled={sending}>
            Yopish
          </Button>
          <Button type="submit" form="notification-test-form" variant="primary" icon={Send} loading={sending}>
            Yuborish
          </Button>
        </>
      }
    >
      <form id="notification-test-form" onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <Field label="Kanal">
          <Select
            value={channel}
            onChange={(v) => {
              setChannel(v as NotificationChannel);
              clearOutcome();
            }}
            options={CHANNEL_OPTIONS}
          />
        </Field>
        {status && !channelReady && <Notice tone="warning">Kanal sozlanmagan — xabar yuborilmaydi.</Notice>}
        <Field label={channel === 'telegram' ? 'Telegram chat ID' : 'Telefon raqami'} required error={fieldError}>
          <Input
            placeholder={channel === 'telegram' ? '123456789 yoki -100…' : '+998 90 123 45 67'}
            value={recipient}
            onChange={(e) => {
              setRecipient(e.target.value);
              clearOutcome();
            }}
            autoComplete="off"
            className="intel-code"
          />
        </Field>
        <Field label="Matn (ixtiyoriy)" hint={`${text.length} / 500`}>
          <Textarea
            placeholder="Bildirishnomalar to'g'ri sozlangan."
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setResult(null);
            }}
            maxLength={500}
            rows={3}
          />
        </Field>
        {sendError && (
          <Notice tone="danger" title="Yuborib bo'lmadi">
            {sendError}
          </Notice>
        )}
        {result &&
          (result.ok ? (
            <Notice tone="success">Xabar yuborildi.</Notice>
          ) : (
            <Notice tone="danger" title="Yuborib bo'lmadi">
              {result.error ?? "Yuborib bo'lmadi"}
            </Notice>
          ))}
      </form>
    </Modal>
  );
}
