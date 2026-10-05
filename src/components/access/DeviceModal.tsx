import { useEffect, useState, type FormEvent } from 'react';
import { Button, Field, Input, Modal, Select } from '../../ui';
import { Checkbox, Notice } from '../settings/kit';
import { useBuildings } from '../../lib/useBuildings';
import {
  DIRECTION_LABELS,
  EMPTY_DEVICE_FORM,
  KIND_LABELS,
  buildDevicePayload,
  deviceToForm,
  validateDeviceForm,
  type AccessDevice,
  type DeviceDirection,
  type DeviceForm,
  type DeviceKind,
} from '../../lib/integrationsApi';

const KIND_HELP: Record<DeviceKind, string> = {
  hikvision:
    "Server qurilmadan hodisalarni o'zi so'rab oladi (ISAPI, HTTP Digest). Qurilma server bilan bir tarmoqda bo'lishi kerak.",
  zkteco:
    "Qurilma yoki oraliq dastur hodisalarni webhook manzilga yuboradi (JSON yoki ADMS ATTLOG matni). Saqlagandan keyin API kalit bir marta ko'rsatiladi.",
  webhook:
    'Istalgan tizim hodisalarni webhook manzilga JSON bilan yuboradi: {events: [{id, time, cardNo, employeeNo, direction, granted}]}.',
};

const KIND_OPTIONS = (Object.keys(KIND_LABELS) as DeviceKind[]).map((k) => ({ value: k, label: KIND_LABELS[k] }));
const DIRECTION_OPTIONS = (Object.keys(DIRECTION_LABELS) as DeviceDirection[]).map((d) => ({ value: d, label: DIRECTION_LABELS[d] }));

export default function DeviceModal({
  open,
  device,
  onClose,
  onSubmit,
}: {
  open: boolean;
  /** null — yangi qurilma. */
  device: AccessDevice | null;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => Promise<void>;
}) {
  const isEdit = device !== null;
  const { buildings } = useBuildings();
  const [form, setForm] = useState<DeviceForm>(EMPTY_DEVICE_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof DeviceForm, string>>>({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(device ? deviceToForm(device) : EMPTY_DEVICE_FORM);
    setErrors({});
    setSubmitError(null);
  }, [open, device]);

  function set<K extends keyof DeviceForm>(key: K, value: DeviceForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const nextErrors = validateDeviceForm(form, isEdit);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSaving(true);
    setSubmitError(null);
    try {
      await onSubmit(buildDevicePayload(form, isEdit));
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Saqlab bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  const isHikvision = form.kind === 'hikvision';

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Qurilmani tahrirlash' : "Yangi qurilma qo'shish"}
      description="Turniket yoki yuz terminali — o'tishlar davomatga yoziladi."
      size="lg"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form="access-device-form" variant="primary" loading={saving}>
            Saqlash
          </Button>
        </>
      }
    >
      <form id="access-device-form" onSubmit={(e) => void handleSubmit(e)} noValidate className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Nomi" required error={errors.name}>
            <Input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Masalan: 1-bino asosiy kirish" maxLength={100} />
          </Field>
          <Field label="Turi" hint={isEdit ? "Turini keyin o'zgartirib bo'lmaydi" : undefined}>
            <Select value={form.kind} disabled={isEdit} onChange={(v) => set('kind', v as DeviceKind)} options={KIND_OPTIONS} />
          </Field>
        </div>
        <Notice tone="neutral">{KIND_HELP[form.kind]}</Notice>

        {isHikvision && (
          <>
            <div className="grid grid-cols-3 gap-4">
              <Field label="IP manzil" required error={errors.ip} className="col-span-2">
                <Input value={form.ip} onChange={(e) => set('ip', e.target.value)} placeholder="192.168.1.50" className="intel-code" />
              </Field>
              <Field label="Port" error={errors.port}>
                <Input value={form.port} onChange={(e) => set('port', e.target.value)} inputMode="numeric" placeholder="80" />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Login" required error={errors.username}>
                <Input value={form.username} onChange={(e) => set('username', e.target.value)} autoComplete="off" />
              </Field>
              <Field label={isEdit ? "Parol (o'zgartirish uchun)" : 'Parol'} required={!isEdit} error={errors.password}>
                <Input
                  type="password"
                  value={form.password}
                  onChange={(e) => set('password', e.target.value)}
                  autoComplete="new-password"
                  placeholder={isEdit && device?.hasPassword ? '•••••• (saqlangan)' : ''}
                />
              </Field>
            </div>
          </>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Yo'nalish"
            hint="“Ikkalasi” — kunning birinchi o'tishi kelish, keyingilari ketish (hodisaning o'z yo'nalishi bo'lsa, u ustun)."
          >
            <Select value={form.direction} onChange={(v) => set('direction', v as DeviceDirection)} options={DIRECTION_OPTIONS} />
          </Field>
          <Field label="Bino">
            <Select
              value={form.buildingId}
              onChange={(v) => set('buildingId', v)}
              placeholder="— Ko'rsatilmagan —"
              options={buildings.map((b) => ({ value: b.id, label: b.name }))}
            />
          </Field>
        </div>

        <div className="flex flex-col gap-3">
          <Checkbox
            label="Davomatga yozilsin"
            description="O'chirilsa, o'tishlar faqat jurnalga yoziladi."
            checked={form.marksAttendance}
            onChange={(e) => set('marksAttendance', e.target.checked)}
          />
          <Checkbox label="Yoqilgan" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
        </div>

        {submitError && <Notice tone="danger">{submitError}</Notice>}
      </form>
    </Modal>
  );
}
