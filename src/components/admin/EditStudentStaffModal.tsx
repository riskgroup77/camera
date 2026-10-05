import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Camera, Loader2 } from 'lucide-react';
import { Avatar, Button, ConfirmDialog, ErrorState, Field, Input, Modal, Select } from '../../ui';
import FaceCapture from './FaceCapture';
import { required } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useFaculties } from '../../lib/useFaculties';
import { formatUzPhone, normalizeUzPhone } from '../../lib/notificationsApi';
import ParentNotifyFields from '../notifications/ParentNotifyFields';
import type { StudentStaffDetail, StudentStaffRecord } from '../../types';

interface FormState {
  fullName: string;
  type: 'talaba' | 'xodim';
  faculty: string;
  course: string;
  group: string;
  position: string;
  pinfl: string;
  passportSeries: string;
  passportNumber: string;
  parentPhone: string;
  parentNotifyEnabled: boolean;
  cardNumber: string;
}

const COURSE_OPTIONS = [1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n}-kurs` }));

function toForm(r: StudentStaffDetail | StudentStaffRecord): FormState {
  const detail = r as Partial<StudentStaffDetail>;
  const isStudent = r.type === 'talaba';
  return {
    fullName: r.fullName,
    type: r.type,
    faculty: r.faculty,
    course: isStudent && r.course ? String(r.course) : '',
    // Kurs ajratib bo'lmagan eski yozuvda butun matn guruh maydoniga tushadi.
    group: isStudent ? (r.course ? (r.group ?? '') : r.groupOrPosition) : '',
    position: isStudent ? '' : r.groupOrPosition,
    pinfl: detail.pinfl ?? '',
    passportSeries: detail.passportSeries ?? '',
    passportNumber: detail.passportNumber ?? '',
    parentPhone: formatUzPhone(detail.parentPhone),
    parentNotifyEnabled: detail.parentNotifyEnabled ?? false,
    cardNumber: detail.cardNumber ?? '',
  };
}

type Errors = Partial<Record<keyof FormState, string>> & { form?: string };

export default function EditStudentStaffModal({
  record,
  onClose,
  onSave,
}: {
  record: StudentStaffRecord | null;
  onClose: () => void;
  onSave: (record: StudentStaffRecord) => void;
}) {
  const { token } = useAuth();
  const { faculties } = useFaculties();
  const formId = useId();
  const [form, setForm] = useState<FormState | null>(record ? toForm(record) : null);
  const [original, setOriginal] = useState<FormState | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [saving, setSaving] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [newFace, setNewFace] = useState<string | null>(null);
  const [parentTelegramLinked, setParentTelegramLinked] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  // Tafsilot so'rovini qayta yuborish uchun (xato bo'lganda JSHSHIR/pasport
  // maydonlari qulflanib qolardi va oynani yopib ochishdan boshqa yo'l yo'q edi).
  const [detailNonce, setDetailNonce] = useState(0);

  useEffect(() => {
    if (!record) return;
    setForm(toForm(record));
    setOriginal(null);
    setErrors({});
    setCapturing(false);
    setNewFace(null);
    setParentTelegramLinked(false);
    setConfirmDiscard(false);
    if (!token) return;
    // JSHSHIR va pasport ro'yxatda yuborilmaydi — faqat tahrirlash ochilganda.
    let cancelled = false;
    setLoadingDetail(true);
    api
      .get<StudentStaffDetail>(`/api/students-staff/${record.id}/details`, token)
      .then((detail) => {
        if (cancelled) return;
        const next = toForm(detail);
        setForm(next);
        setOriginal(next);
        setParentTelegramLinked(Boolean(detail.parentTelegramLinked));
      })
      .catch((err) => {
        if (!cancelled)
          setErrors({ form: err instanceof ApiError ? err.message : "Shaxsiy ma'lumotlarni yuklab bo'lmadi" });
      })
      .finally(() => !cancelled && setLoadingDetail(false));
    return () => {
      cancelled = true;
    };
  }, [record, token, detailNonce]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function validate(f: FormState): Errors {
    const pinflDigits = f.pinfl.replace(/\D/g, '');
    const series = f.passportSeries.trim();
    const number = f.passportNumber.replace(/\D/g, '');
    const next: Errors = {
      fullName: required(f.fullName, "F.I.Sh. kiritilishi shart"),
      faculty: f.faculty ? undefined : 'Fakultetni tanlang',
    };
    if (f.type === 'talaba') {
      if (!f.course && !f.group.trim()) next.course = 'Kursni tanlang';
    } else {
      next.position = required(f.position, 'Lavozim kiritilishi shart');
    }
    if (pinflDigits && pinflDigits.length !== 14) next.pinfl = 'JSHSHIR 14 ta raqam bo‘lishi kerak';
    if ((series || number) && !/^[A-Za-z]{2}$/.test(series)) next.passportSeries = '2 ta harf (masalan AD)';
    if ((series || number) && number.length !== 7) next.passportNumber = '7 ta raqam';
    if (f.type === 'talaba' && f.parentPhone.trim() && !normalizeUzPhone(f.parentPhone)) {
      next.parentPhone = "Raqam noto'g'ri (+998 90 123 45 67)";
    }
    return next;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!record || !form) return;

    const next = validate(form);
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    const payload: Record<string, unknown> = {
      fullName: form.fullName.trim(),
      type: form.type,
      faculty: form.faculty,
    };
    if (form.type === 'talaba') {
      payload.course = form.course ? Number(form.course) : null;
      payload.group = form.group.trim();
      payload.groupOrPosition = form.course ? '' : form.group.trim();
    } else {
      payload.groupOrPosition = form.position.trim();
    }
    // Faqat tafsilot yuklangan va o'zgargan identifikatorlar yuboriladi —
    // tafsilot yuklanmagan bo'lsa, bo'sh maydon mavjud JSHSHIRni o'chirib yubormasin.
    if (original) {
      if (form.pinfl !== original.pinfl) payload.pinfl = form.pinfl;
      if (form.passportSeries !== original.passportSeries || form.passportNumber !== original.passportNumber) {
        payload.passportSeries = form.passportSeries;
        payload.passportNumber = form.passportNumber;
      }
      if (form.cardNumber !== original.cardNumber) payload.cardNumber = form.cardNumber.trim();
      if (form.type === 'talaba') {
        if (form.parentPhone !== original.parentPhone) payload.parentPhone = normalizeUzPhone(form.parentPhone) ?? '';
        if (form.parentNotifyEnabled !== original.parentNotifyEnabled) {
          payload.parentNotifyEnabled = form.parentNotifyEnabled;
        }
      }
    }

    setSaving(true);
    try {
      let updated: StudentStaffRecord = await api.patch<StudentStaffDetail>(
        `/api/students-staff/${record.id}`,
        payload,
        token,
      );
      if (newFace) {
        const blob = await (await fetch(newFace)).blob();
        const data = new FormData();
        data.append('photo', blob, 'face.png');
        updated = await api.postForm<StudentStaffRecord>(`/api/students-staff/${record.id}/biometrics`, data, token);
      }
      onSave(updated);
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Tarmoq xatosi' });
    } finally {
      setSaving(false);
    }
  }

  const facultyOptions = useMemo(() => {
    const options = faculties.map((f) => ({ value: f.name, label: f.name }));
    if (form?.faculty && !options.some((o) => o.value === form.faculty)) options.unshift({ value: form.faculty, label: form.faculty });
    return options;
  }, [faculties, form?.faculty]);

  const isStudent = form?.type === 'talaba';
  const identityLocked = loadingDetail || !original;
  // Saqlanmagan o'zgarish bormi: tafsilot kelgan bo'lsa unga, aks holda
  // ro'yxatdagi yozuvga solishtiramiz.
  const baseline = original ?? (record ? toForm(record) : null);
  const dirty = Boolean(form && baseline && JSON.stringify(form) !== JSON.stringify(baseline)) || Boolean(newFace);

  function requestClose() {
    if (saving) return;
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    onClose();
  }

  return (
    <>
    <Modal
      open={!!record}
      onClose={requestClose}
      title="Ma'lumotlarni tahrirlash"
      description={record ? record.fullName : undefined}
      size="md"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={requestClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={saving} disabled={loadingDetail}>
            Saqlash
          </Button>
        </>
      }
    >
      {form && record && (
        <form id={formId} onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
          {/* Tafsilot yuklanmasa JSHSHIR/pasport maydonlari qulflangan
              qoladi — shu yerdan qayta urinib ko'rish mumkin. */}
          {errors.form && (
            <ErrorState title="Xatolik" message={errors.form} onRetry={identityLocked ? () => setDetailNonce((n) => n + 1) : undefined} />
          )}
          <Field label="F.I.Sh." required error={errors.fullName}>
            <Input value={form.fullName} onChange={(e) => set('fullName', e.target.value)} />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Turi">
              <Select
                value={form.type}
                onChange={(value) => set('type', value as FormState['type'])}
                options={[
                  { value: 'talaba', label: 'Talaba' },
                  { value: 'xodim', label: 'Xodim' },
                ]}
                className="sm:w-full"
              />
            </Field>
            <Field label="Fakultet" required error={errors.faculty}>
              <Select
                value={form.faculty}
                onChange={(value) => set('faculty', value)}
                placeholder="Tanlang"
                options={facultyOptions}
                className="sm:w-full"
              />
            </Field>
          </div>

          {isStudent ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Kurs" required error={errors.course}>
                <Select value={form.course} onChange={(value) => set('course', value)} placeholder="Kursni tanlang" options={COURSE_OPTIONS} className="sm:w-full" />
              </Field>
              <Field label="Guruh" error={errors.group}>
                <Input value={form.group} placeholder="masalan DI-1625" onChange={(e) => set('group', e.target.value)} />
              </Field>
            </div>
          ) : (
            <Field label="Lavozim / kafedra" required error={errors.position}>
              <Input value={form.position} onChange={(e) => set('position', e.target.value)} />
            </Field>
          )}

          <fieldset className="flex min-w-0 flex-col gap-3 rounded-card border border-border bg-surface-2/60 p-3.5">
            <legend className="flex items-center px-1 text-xs font-semibold uppercase tracking-wide text-muted">
              Shaxsni tasdiqlovchi ma&apos;lumot
              {loadingDetail && <Loader2 size={12} className="ml-1.5 animate-spin" aria-label="Yuklanmoqda" />}
            </legend>
            <Field label="JSHSHIR" error={errors.pinfl}>
              <Input
                inputMode="numeric"
                autoComplete="off"
                maxLength={20}
                value={form.pinfl}
                disabled={identityLocked}
                onChange={(e) => set('pinfl', e.target.value)}
              />
            </Field>
            <div className="grid grid-cols-[6rem_1fr] gap-3">
              <Field label="Seriya" error={errors.passportSeries}>
                <Input
                  autoComplete="off"
                  maxLength={2}
                  value={form.passportSeries}
                  disabled={identityLocked}
                  onChange={(e) => set('passportSeries', e.target.value.toUpperCase())}
                />
              </Field>
              <Field label="Pasport raqami" error={errors.passportNumber}>
                <Input
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={7}
                  value={form.passportNumber}
                  disabled={identityLocked}
                  onChange={(e) => set('passportNumber', e.target.value)}
                />
              </Field>
            </div>
            <p className="text-xs text-muted">Bo‘sh qoldirilsa, maydon o‘chiriladi.</p>
          </fieldset>

          <ParentNotifyFields
            key={record.id}
            isStudent={isStudent}
            value={{
              parentPhone: form.parentPhone,
              parentNotifyEnabled: form.parentNotifyEnabled,
              cardNumber: form.cardNumber,
            }}
            onChange={(next) => setForm((f) => (f ? { ...f, ...next } : f))}
            errors={{ parentPhone: errors.parentPhone, cardNumber: errors.cardNumber }}
            disabled={identityLocked}
            personId={record.type === 'talaba' ? record.id : undefined}
            telegramLinked={parentTelegramLinked}
            onTelegramUnlinked={() => setParentTelegramLinked(false)}
          />

          <div className="rounded-card border border-border bg-surface-2/60 p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <Avatar name={record.fullName} src={newFace ?? record.biometricPhotoUrl} size="md" status={newFace || record.biometricsStatus === 'tasdiqlangan' ? 'success' : null} />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-fg">Yuz rasmi</p>
                  <p className="text-xs text-muted">
                    {newFace
                      ? 'Yangi rasm — saqlashda almashtiriladi'
                      : record.biometricsStatus === 'tasdiqlangan'
                        ? `Tasdiqlangan${record.confirmedLabel ? ` · ${record.confirmedLabel}` : ''}`
                        : 'Tasdiqlanmagan — davomatda tanilmaydi'}
                  </p>
                </div>
              </div>
              {!capturing && (
                <Button size="sm" icon={Camera} onClick={() => setCapturing(true)}>
                  {newFace || record.biometricsStatus === 'tasdiqlangan' ? 'Yuzni yangilash' : 'Yuzni olish'}
                </Button>
              )}
            </div>
            {capturing && (
              <div className="mt-3 flex flex-col items-center gap-2">
                <FaceCapture
                  onConfirm={(dataUrl) => {
                    setNewFace(dataUrl);
                    setCapturing(false);
                  }}
                />
                <Button size="sm" variant="ghost" onClick={() => setCapturing(false)}>
                  Bekor qilish
                </Button>
              </div>
            )}
          </div>
        </form>
      )}
    </Modal>
      <ConfirmDialog
        open={confirmDiscard}
        title="O'zgarishlar saqlanmadi"
        message="O'zgarishlar va yangi yuz surati yo'qoladi."
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
