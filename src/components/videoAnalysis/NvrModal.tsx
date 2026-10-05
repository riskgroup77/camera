import { useEffect, useState, type FormEvent } from 'react';
import { Button, Field, Input, Modal, Select } from '../../ui';
import { Checkbox, Notice } from '../settings/kit';
import { EMPTY_NVR_FORM, buildNvrPayload, nvrToForm, validateNvrForm, type NvrForm } from '../../lib/nvrForm';
import type { Nvr, NvrInput } from '../../lib/videoAnalysisApi';

const KIND_OPTIONS = [
  { value: 'hikvision', label: 'Hikvision NVR (tarmoq)' },
  { value: 'fayl', label: 'Eksport qilingan yozuvlar papkasi' },
];
const STREAM_OPTIONS = [
  { value: 'main', label: 'Asosiy oqim (aniqroq yuz)' },
  { value: 'sub', label: 'Sub-oqim (yengil, NVR yozsa)' },
];
const FETCH_OPTIONS = [
  { value: 'download', label: 'Yuklab olish (tez, ISAPI)' },
  { value: 'rtsp', label: 'RTSP playback (real vaqt tezligida)' },
];

export default function NvrModal({
  open,
  nvr,
  onClose,
  onSubmit,
}: {
  open: boolean;
  /** null — yangi NVR. */
  nvr: Nvr | null;
  onClose: () => void;
  onSubmit: (body: NvrInput) => Promise<void>;
}) {
  const isEdit = nvr !== null;
  const [form, setForm] = useState<NvrForm>(EMPTY_NVR_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof NvrForm, string>>>({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(nvr ? nvrToForm(nvr) : EMPTY_NVR_FORM);
    setErrors({});
    setSubmitError(null);
  }, [open, nvr]);

  function set<K extends keyof NvrForm>(key: K, value: NvrForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next = validateNvrForm(form);
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true);
    setSubmitError(null);
    try {
      await onSubmit(buildNvrPayload(form, isEdit));
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Saqlab bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  const hik = form.kind === 'hikvision';
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'NVR ni tahrirlash' : "NVR qo'shish"}
      description="Kun oxirida kameralar yozuvi shu qurilmadan olinib tahlil qilinadi."
      size="lg"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form="nvr-form" variant="primary" loading={saving}>
            Saqlash
          </Button>
        </>
      }
    >
      <form id="nvr-form" onSubmit={(e) => void handleSubmit(e)} noValidate className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Nomi" required error={errors.name}>
            <Input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Masalan: 1-bino NVR" maxLength={120} />
          </Field>
          <Field label="Turi" hint={isEdit ? "Turini keyin o'zgartirib bo'lmaydi" : undefined}>
            <Select value={form.kind} disabled={isEdit} onChange={(v) => set('kind', v as NvrForm['kind'])} options={KIND_OPTIONS} />
          </Field>
        </div>

        {hik ? (
          <>
            <div className="grid grid-cols-4 gap-4">
              <Field label="IP manzil" required error={errors.ip} className="col-span-2">
                <Input value={form.ip} onChange={(e) => set('ip', e.target.value)} placeholder="192.168.0.94" className="intel-code" />
              </Field>
              <Field label="HTTP port" error={errors.httpPort}>
                <Input value={form.httpPort} onChange={(e) => set('httpPort', e.target.value)} inputMode="numeric" />
              </Field>
              <Field label="RTSP port" error={errors.rtspPort}>
                <Input value={form.rtspPort} onChange={(e) => set('rtspPort', e.target.value)} inputMode="numeric" />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Login">
                <Input value={form.username} onChange={(e) => set('username', e.target.value)} autoComplete="off" />
              </Field>
              <Field label={isEdit ? "Parol (o'zgartirish uchun)" : 'Parol'}>
                <Input
                  type="password"
                  value={form.password}
                  onChange={(e) => set('password', e.target.value)}
                  autoComplete="new-password"
                  placeholder={isEdit && nvr?.hasPassword ? '•••••• (saqlangan)' : ''}
                />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Qaysi yozuv">
                <Select value={form.stream} onChange={(v) => set('stream', v as NvrForm['stream'])} options={STREAM_OPTIONS} />
              </Field>
              <Field label="Olish usuli" hint="Yuklab olish ishlamasa, avtomatik RTSP ga o'tadi">
                <Select value={form.fetchMode} onChange={(v) => set('fetchMode', v as NvrForm['fetchMode'])} options={FETCH_OPTIONS} />
              </Field>
            </div>
            <Checkbox
              label="NVR vaqti mahalliy soatda"
              description="Ko'p Hikvision NVR'lar playback vaqtini o'z mahalliy soatida kutadi. Yozuvlar 5 soat siljib kelsa — o'chiring."
              checked={form.localTime}
              onChange={(e) => set('localTime', e.target.checked)}
            />
          </>
        ) : (
          <>
            <Field label="Papka" required error={errors.basePath} hint="Ichida kanal raqamli papkalar: 1/, 2/ … fayllar: YYYYMMDD_HHMMSS.mp4">
              <Input value={form.basePath} onChange={(e) => set('basePath', e.target.value)} placeholder="/data/nvr-eksport" className="intel-code" />
            </Field>
            <Notice tone="neutral">
              NVR tarmoqqa ulanmagan bo'lsa, yozuvni USB orqali eksport qilib, serverdagi shu papkaga joylang — tahlil xuddi NVR'dagidek ishlaydi.
            </Notice>
          </>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Bir vaqtdagi oqimlar" error={errors.maxStreams} hint="NVR bir vaqtda beradigan playback soni (odatda 8–16)">
            <Input value={form.maxStreams} onChange={(e) => set('maxStreams', e.target.value)} inputMode="numeric" />
          </Field>
          <div className="flex items-end pb-2">
            <Checkbox label="Yoqilgan" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
          </div>
        </div>

        {submitError && <Notice tone="danger">{submitError}</Notice>}
      </form>
    </Modal>
  );
}
