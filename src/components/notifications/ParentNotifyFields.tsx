import { useState } from 'react';
import { Link2, Unlink } from 'lucide-react';
import { Button, Field, Input, cn } from '../../ui';
import TelegramLinkBox from './TelegramLinkBox';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { normalizeUzPhone, notificationsApi, type TelegramLink } from '../../lib/notificationsApi';

export interface ParentFieldsValue {
  parentPhone: string;
  parentNotifyEnabled: boolean;
  cardNumber: string;
}

/** Talaba/xodim oynalaridagi "Ota-ona va turniket" bo'limi.
 *
 *  Ota-ona qismi faqat talabada ko'rinadi. `personId` berilsa (tahrirlash)
 *  ota-ona Telegramini bog'lash havolasini yaratish ham mumkin — yangi
 *  yozuvda havola saqlangandan keyin yaratiladi. */
export default function ParentNotifyFields({
  isStudent,
  value,
  onChange,
  errors,
  disabled = false,
  personId,
  telegramLinked = false,
  onTelegramUnlinked,
}: {
  isStudent: boolean;
  value: ParentFieldsValue;
  onChange: (next: ParentFieldsValue) => void;
  errors?: Partial<Record<'parentPhone' | 'cardNumber', string>>;
  disabled?: boolean;
  personId?: string;
  telegramLinked?: boolean;
  onTelegramUnlinked?: () => void;
}) {
  const { token } = useAuth();
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  function set<K extends keyof ParentFieldsValue>(key: K, v: ParentFieldsValue[K]) {
    onChange({ ...value, [key]: v });
  }

  async function createLink() {
    if (!personId) return;
    setBusy(true);
    setLinkError(null);
    try {
      setLink(await notificationsApi.parentTelegramLink(personId, token));
    } catch (err) {
      setLinkError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    if (!personId) return;
    setBusy(true);
    setLinkError(null);
    try {
      await notificationsApi.unlinkParentTelegram(personId, token);
      setLink(null);
      onTelegramUnlinked?.();
    } catch (err) {
      setLinkError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="flex min-w-0 flex-col gap-3 border border-border bg-surface-2/60 p-3">
      <legend className="intel-micro px-1">{isStudent ? 'Ota-ona va turniket' : 'Turniket'}</legend>
      {isStudent && (
        <>
          <Field label="Ota-ona telefoni" error={errors?.parentPhone}>
            <Input
              type="tel"
              placeholder="+998 90 123 45 67"
              autoComplete="off"
              value={value.parentPhone}
              disabled={disabled}
              onChange={(e) => set('parentPhone', e.target.value)}
            />
          </Field>
          <label className={cn('flex items-start gap-2.5 text-sm', disabled && 'opacity-60')}>
            <input
              type="checkbox"
              checked={value.parentNotifyEnabled}
              disabled={disabled}
              onChange={(e) => set('parentNotifyEnabled', e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-border-strong accent-primary"
            />
            <span className="text-fg">
              Ota-onaga xabar yuborilsin
              <span className="block text-xs text-muted">
                Institutga kelganda va kun oxirida kelmaganda (Telegram bog&apos;langan bo&apos;lsa Telegram, aks holda SMS).
              </span>
            </span>
          </label>
          {/* Yoqilgan, lekin yuboradigan joy yo'q: na yaroqli telefon, na
              bog'langan Telegram. Ilgari bu JIMGINA saqlanardi va ota-ona
              hech qachon xabar olmasdi — sababini hech kim bilmasdi. */}
          {value.parentNotifyEnabled && !telegramLinked && !normalizeUzPhone(value.parentPhone) && (
            <p role="alert" className="border border-warning/40 bg-warning-soft px-2.5 py-2 text-xs font-medium text-warning">
              Xabar yuborish yoqilgan, lekin manzil yo&apos;q: yaroqli telefon raqami (+998XXXXXXXXX) kiriting yoki ota-ona Telegramini
              bog&apos;lang — aks holda hech qanday xabar bormaydi.
            </p>
          )}
          {!personId && (
            <p className="text-xs text-muted">Ota-ona Telegramini bog&apos;lash havolasi yozuv saqlangandan keyin tahrirlash oynasida yaratiladi.</p>
          )}
          {personId && (
            <div className="flex flex-col gap-2">
              {telegramLinked ? (
                <div className="flex flex-wrap items-center justify-between gap-2 border border-success/30 bg-success-soft px-3 py-2">
                  <span className="text-xs font-semibold text-success">Ota-ona Telegrami bog&apos;langan</span>
                  {/* `disabled` (forma saqlanmoqda / faqat o'qish) uzish
                      tugmasiga ham tegishli — ilgari faqat bog'lash tugmasida
                      edi va yozuv qulflangan holatda ham uzib yuborish
                      mumkin bo'lardi. */}
                  <Button size="sm" variant="ghost" icon={Unlink} onClick={unlink} loading={busy} disabled={disabled} className="text-danger hover:text-danger">
                    Uzish
                  </Button>
                </div>
              ) : link ? (
                <TelegramLinkBox link={link} hint="Havolani ota-onaga yuboring" />
              ) : (
                <Button size="sm" icon={Link2} onClick={createLink} loading={busy} disabled={disabled}>
                  Ota-ona Telegramini bog&apos;lash
                </Button>
              )}
              {linkError && (
                <p role="alert" className="text-xs font-medium text-danger">
                  {linkError}
                </p>
              )}
            </div>
          )}
        </>
      )}
      <Field label="Karta raqami" hint="Ixtiyoriy" error={errors?.cardNumber}>
        <Input
          autoComplete="off"
          maxLength={64}
          placeholder="Turniket raqami"
          value={value.cardNumber}
          disabled={disabled}
          onChange={(e) => set('cardNumber', e.target.value)}
        />
      </Field>
    </fieldset>
  );
}
