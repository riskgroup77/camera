import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Check, MessageSquare, Send } from 'lucide-react';
import { Button, CodeText, Field, Input, Modal, Select, cn, focusRing } from '../../ui';
import { Checkbox, ChoiceCards, Notice } from '../settings/kit';
import RecipientChipsInput from './RecipientChipsInput';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useAiModules } from '../../lib/useAiModules';
import { useBuildings } from '../../lib/useBuildings';
import {
  KIND_OPTIONS,
  SEVERITY_OPTIONS,
  notificationsApi,
  validateRecipient,
  type NotificationChannel,
  type NotificationKind,
  type NotificationRule,
  type NotificationRuleInput,
  type NotificationStatus,
} from '../../lib/notificationsApi';
import type { EventSeverity } from '../../types';

interface FormState {
  name: string;
  enabled: boolean;
  channel: NotificationChannel;
  recipients: string[];
  kinds: NotificationKind[];
  moduleCodes: number[];
  buildingIds: string[];
  minSeverity: EventSeverity | '';
}

const EMPTY: FormState = {
  name: '',
  enabled: true,
  channel: 'telegram',
  recipients: [],
  kinds: ['event'],
  moduleCodes: [],
  buildingIds: [],
  minSeverity: '',
};

const CHANNEL_OPTIONS = [
  { value: 'telegram' as const, label: 'Telegram', description: 'Chat, guruh yoki kanal', icon: Send },
  { value: 'sms' as const, label: 'SMS', description: 'Eskiz.uz orqali telefon raqamiga', icon: MessageSquare },
];

function toForm(rule: NotificationRule | null): FormState {
  if (!rule) return EMPTY;
  return {
    name: rule.name,
    enabled: rule.enabled,
    channel: rule.channel,
    recipients: rule.recipients,
    kinds: rule.kinds,
    moduleCodes: rule.moduleCodes ?? [],
    buildingIds: rule.buildingIds ?? [],
    minSeverity: rule.minSeverity ?? '',
  };
}

type Errors = Partial<Record<'name' | 'recipients' | 'kinds' | 'form', string>>;

/** Maydon guruhlari sarlavhasi — bosh harfli mikro-yorliq. */
const legendClass = 'intel-micro !text-fg mb-2 block';

/** Qoida yaratish/tahrirlash. `rule` = null — yangi qoida. */
export default function NotificationRuleModal({
  open,
  rule,
  status = null,
  onClose,
  onSaved,
}: {
  open: boolean;
  rule: NotificationRule | null;
  /** Kanal holati — tanlangan kanal serverda sozlanmagan bo'lsa ogohlantirish uchun. */
  status?: NotificationStatus | null;
  onClose: () => void;
  onSaved: (rule: NotificationRule) => void;
}) {
  const { token } = useAuth();
  const { modules } = useAiModules();
  const { buildings } = useBuildings();
  const [form, setForm] = useState<FormState>(toForm(rule));
  const [errors, setErrors] = useState<Errors>({});
  const [saving, setSaving] = useState(false);
  // "Qabul qiluvchilar" maydonida hali chip'ga aylanmagan matn. Ilgari u
  // saqlashda JIMGINA yo'qolardi (noto'g'ri raqam yozilib, Enter bosilmasa
  // qoida usiz saqlanardi) — endi saqlash to'xtatiladi.
  const [recipientDraft, setRecipientDraft] = useState('');
  // Kanal almashtirilganda mos kelmaydigan qabul qiluvchilar olib tashlanadi.
  // Ilgari bu JIMGINA bo'lardi: SMS qoidasiga o'tib qaytgan odam Telegram
  // chat ID larini yo'qotib, sababini bilmay qolardi.
  const [droppedRecipients, setDroppedRecipients] = useState<string[]>([]);

  useEffect(() => {
    if (open) {
      setForm(toForm(rule));
      setErrors({});
      setRecipientDraft('');
      setDroppedRecipients([]);
    }
  }, [open, rule]);

  const channelUnconfigured = status ? (form.channel === 'telegram' ? !status.telegramConfigured : !status.smsConfigured) : false;
  const sortedModules = useMemo(() => [...modules].sort((a, b) => a.code - b.code), [modules]);
  const eventKindsSelected = form.kinds.includes('event') || form.kinds.includes('event_overdue');
  const buildingFilterApplies = eventKindsSelected || form.kinds.some((k) => k === 'camera_offline' || k === 'camera_online');

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  /** Xato faqat keyingi "Saqlash"da yangilanardi — odam kamchilikni
   *  tuzatgandan keyin ham qizil yozuv turaverardi. Endi darhol ketadi. */
  function clearError(key: keyof Errors) {
    setErrors((prev) => (prev[key] ? { ...prev, [key]: undefined } : prev));
  }

  function toggle<T>(list: T[], item: T): T[] {
    return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
  }

  function changeChannel(channel: NotificationChannel) {
    // Boshqa kanal qoidasiga mos kelmaydigan qabul qiluvchilar olib tashlanadi
    // — va nimasi olib tashlangani aytiladi.
    //
    // Hisob-kitob `setForm` YANGILOVCHISIDAN TASHQARIDA: yangilovchi sof
    // bo'lishi shart, ichida boshqa setState chaqirilsa StrictMode ikki
    // marta ishlatib, `droppedRecipients` ni ikki xil natija bilan yozardi.
    const kept = form.recipients.filter((r) => validateRecipient(channel, r)[1] === null);
    const dropped = form.recipients.filter((r) => !kept.includes(r));
    setDroppedRecipients(dropped);
    setForm((f) => ({ ...f, channel, recipients: kept }));
    if (kept.length > 0) setErrors((prev) => ({ ...prev, recipients: undefined }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next: Errors = {
      name: form.name.trim().length < 2 ? 'Qoida nomini kiriting' : undefined,
      recipients: recipientDraft.trim()
        ? `«${recipientDraft.trim()}» hali qo'shilmadi — Enter bosing yoki maydonni tozalang`
        : form.recipients.length === 0
          ? 'Kamida bitta qabul qiluvchi kiriting'
          : undefined,
      kinds: form.kinds.length === 0 ? 'Kamida bitta signal turini tanlang' : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    const body: NotificationRuleInput = {
      name: form.name.trim(),
      enabled: form.enabled,
      channel: form.channel,
      recipients: form.recipients,
      kinds: form.kinds,
      moduleCodes: eventKindsSelected && form.moduleCodes.length ? form.moduleCodes : null,
      buildingIds: buildingFilterApplies && form.buildingIds.length ? form.buildingIds : null,
      minSeverity: eventKindsSelected && form.minSeverity ? form.minSeverity : null,
    };
    setSaving(true);
    try {
      const saved = rule ? await notificationsApi.updateRule(rule.id, body, token) : await notificationsApi.createRule(body, token);
      onSaved(saved);
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Tarmoq xatosi' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={rule ? 'Qoidani tahrirlash' : 'Yangi qoida'}
      description="Kim, qaysi kanal, qanday signal."
      size="lg"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form="notification-rule-form" variant="primary" loading={saving}>
            Saqlash
          </Button>
        </>
      }
    >
      <form id="notification-rule-form" onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field label="Qoida nomi" required error={errors.name}>
            <Input
              placeholder="Masalan: Navbatchilar"
              value={form.name}
              onChange={(e) => {
                set('name', e.target.value);
                clearError('name');
              }}
              maxLength={120}
            />
          </Field>
          <Checkbox
            label="Yoqilgan"
            checked={form.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
            className="border border-border px-3 py-2 sm:mb-0"
          />
        </div>

        <fieldset>
          <legend className={legendClass}>Kanal</legend>
          <ChoiceCards name="notification-channel" value={form.channel} onChange={changeChannel} options={CHANNEL_OPTIONS} />
        </fieldset>

        {/* Sahifadagi ogohlantirish faqat IKKALA kanal ham sozlanmaganda
            chiqardi. Telegram sozlangan-u SMS yo'q bo'lsa, odam SMS qoidasini
            yaratib qo'yib, nega xabar kelmasligini bilmay qolardi. */}
        {channelUnconfigured && (
          <Notice tone="warning">
            {`«${form.channel === 'sms' ? 'SMS' : 'Telegram'}» kanali sozlanmagan — xabar yuborilmaydi.`}
          </Notice>
        )}

        {droppedRecipients.length > 0 && (
          <Notice tone="warning">
            {`Kanal almashtirilgani uchun ${droppedRecipients.length} ta qabul qiluvchi olib tashlandi: `}
            <span className="intel-code">{droppedRecipients.join(', ')}</span>
            {` — ular ${form.channel === 'sms' ? 'SMS' : 'Telegram'} uchun yaroqsiz.`}
          </Notice>
        )}

        <RecipientChipsInput
          channel={form.channel}
          value={form.recipients}
          onChange={(next) => {
            set('recipients', next);
            if (next.length) clearError('recipients');
          }}
          onDraftChange={(draft) => {
            setRecipientDraft(draft);
            if (!draft.trim()) clearError('recipients');
          }}
          error={errors.recipients}
        />

        <fieldset>
          <legend className={legendClass}>
            Signal turlari
            <span className="ml-0.5 text-danger" aria-hidden="true">
              *
            </span>
          </legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {KIND_OPTIONS.map((kind) => (
              <Checkbox
                key={kind.value}
                label={kind.label}
                description={kind.hint}
                checked={form.kinds.includes(kind.value)}
                onChange={() => {
                  const next = toggle(form.kinds, kind.value);
                  set('kinds', next);
                  if (next.length) clearError('kinds');
                }}
                className={cn(
                  'border px-3 py-2 transition-colors',
                  form.kinds.includes(kind.value) ? 'border-primary/40 bg-primary-soft/50' : 'border-border hover:border-border-strong',
                )}
              />
            ))}
          </div>
          {errors.kinds && (
            <p role="alert" className="mt-1.5 text-xs font-medium text-danger">
              {errors.kinds}
            </p>
          )}
        </fieldset>

        {eventKindsSelected && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Eng kam og'irlik" hint="Faqat AI hodisalari">
              <Select
                value={form.minSeverity}
                onChange={(v) => set('minSeverity', v as EventSeverity | '')}
                options={SEVERITY_OPTIONS}
                placeholder="Cheklov yo'q"
              />
            </Field>
            <fieldset className="min-w-0">
              <legend className={legendClass}>
                AI modullari{' '}
                <span className="font-normal text-muted">({form.moduleCodes.length ? `${form.moduleCodes.length} ta tanlangan` : 'hammasi'})</span>
              </legend>
              <div className="max-h-44 divide-y divide-border overflow-y-auto border border-border bg-surface-2">
                {sortedModules.length === 0 && <p className="px-2 py-1 text-xs text-muted">Modullar yuklanmoqda…</p>}
                {sortedModules.map((m) => (
                  <label
                    key={m.code}
                    className="flex cursor-pointer items-center gap-2 px-2 py-1 text-[13px] hover:bg-surface"
                  >
                    <input
                      type="checkbox"
                      checked={form.moduleCodes.includes(m.code)}
                      onChange={() => set('moduleCodes', toggle(form.moduleCodes, m.code))}
                      className={cn('h-3.5 w-3.5 shrink-0 rounded accent-primary', focusRing)}
                    />
                    <CodeText className="text-[11px] text-subtle">#{m.code}</CodeText>
                    <span className="truncate text-fg">{m.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        )}

        {buildingFilterApplies && buildings.length > 0 && (
          <fieldset>
            <legend className={legendClass}>
              Binolar{' '}
              <span className="font-normal text-muted">({form.buildingIds.length ? `${form.buildingIds.length} ta tanlangan` : 'hammasi'})</span>
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {buildings.map((b) => {
                const active = form.buildingIds.includes(b.id);
                return (
                  <button
                    key={b.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => set('buildingIds', toggle(form.buildingIds, b.id))}
                    className={cn(
                      'inline-flex h-7 items-center gap-1.5 border px-2.5 text-[13px] transition-colors',
                      active ? 'border-primary bg-primary-soft text-primary' : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                      focusRing,
                    )}
                  >
                    {active && <Check size={13} aria-hidden="true" />}
                    {b.name}
                  </button>
                );
              })}
            </div>
          </fieldset>
        )}

        {errors.form && <Notice tone="danger">{errors.form}</Notice>}
      </form>
    </Modal>
  );
}
