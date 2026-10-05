import { useId, useState, type FormEvent } from 'react';
import { Check } from 'lucide-react';
import { Button, ConfirmDialog, ErrorState, Field, Input, Modal, Select, cn } from '../../ui';
import { required, minLength } from '../../lib/validation';
import PassportUploadStep from './PassportUploadStep';
import FaceCapture from './FaceCapture';
import FaceMatchStep from './FaceMatchStep';
import { ApiError, api, buildQuery } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useFaculties } from '../../lib/useFaculties';
import { normalizeUzPhone } from '../../lib/notificationsApi';
import ParentNotifyFields, { type ParentFieldsValue } from '../notifications/ParentNotifyFields';
import type { StudentStaffRecord } from '../../types';

interface FormState extends ParentFieldsValue {
  fullName: string;
  type: 'talaba' | 'xodim' | '';
  faculty: string;
  groupOrPosition: string;
}

const EMPTY_FORM: FormState = {
  fullName: '',
  type: '',
  faculty: '',
  groupOrPosition: '',
  parentPhone: '',
  parentNotifyEnabled: false,
  cardNumber: '',
};

const STEPS = ["Ma'lumotlar", 'Pasport', 'Yuz skani', 'Tekshiruv'] as const;

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-5 flex items-center" aria-label={`Qadam ${step} / ${STEPS.length}`}>
      {STEPS.map((label, i) => {
        const n = i + 1;
        const state = n < step ? 'done' : n === step ? 'active' : 'pending';
        return (
          <li key={label} className="flex flex-1 items-center last:flex-none" aria-current={state === 'active' ? 'step' : undefined}>
            <div className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold tabular-nums',
                  state === 'done' && 'bg-primary text-primary-fg',
                  state === 'active' && 'bg-primary-soft text-primary ring-2 ring-primary',
                  state === 'pending' && 'bg-surface-2 text-subtle',
                )}
              >
                {state === 'done' ? <Check size={14} aria-hidden="true" /> : n}
              </div>
              <span className={cn('whitespace-nowrap text-[11px] font-medium', state === 'pending' ? 'text-subtle' : 'text-fg')}>{label}</span>
            </div>
            {n < STEPS.length && <div className={cn('mx-2 mb-4 h-0.5 flex-1 rounded-full', n < step ? 'bg-primary' : 'bg-surface-3')} />}
          </li>
        );
      })}
    </ol>
  );
}

export default function AddStudentStaffModal({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (record: StudentStaffRecord) => void;
}) {
  const { token } = useAuth();
  const { faculties } = useFaculties();
  const formId = useId();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [passportPhoto, setPassportPhoto] = useState<string | null>(null);
  const [passportFileName, setPassportFileName] = useState<string | null>(null);
  const [capturedFace, setCapturedFace] = useState<string | null>(null);
  const [matchResult, setMatchResult] = useState<{ score: number; passed: boolean } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Dublikatdan himoya: bazada o'xshash ismli odamlar, tanlangan mavjud yozuv
  // va "bu boshqa odam" tasdig'i. Ro'yxatdagi xodimni qayta qo'shish bitta
  // odamni ikki yozuvga bo'lib yuborardi (scripts/merge_duplicate_people.py).
  const [similar, setSimilar] = useState<StudentStaffRecord[] | null>(null);
  const [existing, setExisting] = useState<StudentStaffRecord | null>(null);
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const [checking, setChecking] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    if (key === 'fullName' || key === 'type') {
      setSimilar(null);
      setExisting(null);
      setAllowDuplicate(false);
    }
  }

  function resetAll() {
    setStep(1);
    setForm(EMPTY_FORM);
    setErrors({});
    setPassportPhoto(null);
    setPassportFileName(null);
    setCapturedFace(null);
    setMatchResult(null);
    setSaveError(null);
    setSimilar(null);
    setExisting(null);
    setAllowDuplicate(false);
  }

  function handleClose() {
    resetAll();
    setConfirmDiscard(false);
    onClose();
  }

  /** Sehrgar uzun: pasport yuklangan va yuz olingan bo'lsa, tasodifiy
   *  yopilish butun ishni yo'qotadi. Shuning uchun so'raymiz. */
  function requestClose() {
    if (saving) return;
    const started = step > 1 || Boolean(form.fullName.trim() || form.type || form.faculty || form.groupOrPosition.trim());
    if (started) {
      setConfirmDiscard(true);
      return;
    }
    handleClose();
  }

  function validateStep1(): boolean {
    const next: typeof errors = {
      fullName: required(form.fullName) ?? minLength(form.fullName, 5, "F.I.Sh. to'liq kiritilishi kerak"),
      type: form.type ? undefined : 'Turini tanlang',
      faculty: form.faculty ? undefined : 'Fakultetni tanlang',
      groupOrPosition: required(form.groupOrPosition, 'Guruh yoki lavozim kiritilishi shart'),
      parentPhone:
        form.type === 'talaba' && form.parentPhone.trim() && !normalizeUzPhone(form.parentPhone)
          ? "Raqam noto'g'ri (+998 90 123 45 67)"
          : undefined,
    };
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  async function handleStep1Submit(e: FormEvent) {
    e.preventDefault();
    if (!validateStep1()) return;
    if (existing || allowDuplicate) {
      setStep(2);
      return;
    }
    setChecking(true);
    try {
      const found = await api.get<StudentStaffRecord[]>(
        `/api/students-staff/similar${buildQuery({ fullName: form.fullName.trim(), type: form.type })}`,
        token,
      );
      if (found.length > 0) {
        setSimilar(found);
        return;
      }
    } catch {
      // Tekshiruv ishlamasa ham davom etiladi — saqlashda backend baribir tekshiradi
    } finally {
      setChecking(false);
    }
    setStep(2);
  }

  function chooseExisting(record: StudentStaffRecord) {
    setExisting(record);
    setSimilar(null);
    setStep(2);
  }

  function confirmNewPerson() {
    setAllowDuplicate(true);
    setSimilar(null);
    setStep(2);
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      // Mavjud odam tanlangan bo'lsa — yangi yozuv yaratilmaydi, yuz o'shanga biriktiriladi
      const record =
        existing ??
        (await api.post<StudentStaffRecord>(
          '/api/students-staff',
          {
            fullName: form.fullName.trim(),
            type: form.type as 'talaba' | 'xodim',
            faculty: form.faculty,
            groupOrPosition: form.groupOrPosition.trim(),
            biometricsStatus: matchResult?.passed ? 'tasdiqlangan' : 'kutilmoqda',
            allowDuplicate,
            parentPhone: form.type === 'talaba' ? normalizeUzPhone(form.parentPhone) : null,
            parentNotifyEnabled: form.type === 'talaba' && form.parentNotifyEnabled,
            cardNumber: form.cardNumber.trim() || null,
          },
          token,
        ));

      // Faqat mos kelgan yuz saqlanadi — "qo'lda tekshirish" yo'li orqali
      // yaratilgan yozuv uchun rasm/embedding hali yo'q, chunki mos kelish
      // tasdiqlanmagan (biometrics_status = 'kutilmoqda' shu holatni aks
      // ettiradi, keyinroq operator qo'lda ko'rib chiqishi kerak).
      let finalRecord = record;
      if (matchResult?.passed && capturedFace) {
        const photoBlob = await (await fetch(capturedFace)).blob();
        const form2 = new FormData();
        form2.append('photo', photoBlob, 'face.png');
        finalRecord = await api.postForm<StudentStaffRecord>(
          `/api/students-staff/${record.id}/biometrics`,
          form2,
          token,
        );
      }

      onAdd(finalRecord);
      handleClose();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setSaving(false);
    }
  }

  const hasSimilar = Boolean(similar && similar.length > 0);

  const footer =
    step === 1 ? (
      <>
        <Button onClick={requestClose}>Bekor qilish</Button>
        {!hasSimilar && (
          <Button type="submit" form={formId} variant="primary" loading={checking}>
            {checking ? 'Tekshirilmoqda…' : 'Keyingi'}
          </Button>
        )}
      </>
    ) : step === 2 ? (
      <>
        <Button onClick={() => setStep(1)} className="mr-auto">
          Orqaga
        </Button>
        <Button onClick={requestClose}>Bekor qilish</Button>
        {/* O'chirilgan tugma sababi aytiladi — ilgari u shunchaki bosilmasdi. */}
        <Button
          variant="primary"
          disabled={!passportPhoto}
          title={passportPhoto ? undefined : 'Avval pasport nusxasini yuklang'}
          onClick={() => setStep(3)}
        >
          Keyingi
        </Button>
      </>
    ) : step === 3 ? (
      <>
        <Button onClick={() => setStep(2)} className="mr-auto">
          Orqaga
        </Button>
        <Button onClick={requestClose}>Bekor qilish</Button>
      </>
    ) : (
      <>
        <Button onClick={() => setStep(3)} disabled={saving} className="mr-auto">
          Orqaga
        </Button>
        {matchResult && !matchResult.passed && !existing && (
          <Button variant="ghost" disabled={saving} onClick={handleSave}>
            Qo&apos;lda tekshirish uchun saqlash
          </Button>
        )}
        <Button
          variant="primary"
          disabled={!matchResult?.passed}
          title={matchResult?.passed ? undefined : "Yuz pasportga mos kelmadi"}
          loading={saving}
          onClick={handleSave}
        >
          Saqlash
        </Button>
      </>
    );

  return (
    <>
    <Modal
      open={open}
      onClose={requestClose}
      title="Yangi shaxs qo'shish"
      description="Ma'lumot, pasport va yuz surati."
      size="md"
      dismissible={false}
      footer={footer}
    >
      <Stepper step={step} />

      {step === 1 && (
        <form id={formId} onSubmit={handleStep1Submit} noValidate className="flex flex-col gap-4">
          <Field label="F.I.Sh." required error={errors.fullName}>
            <Input placeholder="Karimova Dildora Baxtiyorovna" value={form.fullName} onChange={(e) => set('fullName', e.target.value)} autoFocus />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Turi" required error={errors.type}>
              <Select
                value={form.type}
                onChange={(value) => set('type', value as FormState['type'])}
                placeholder="Tanlang"
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
                options={faculties.map((f) => ({ value: f.name, label: f.name }))}
                className="sm:w-full"
              />
            </Field>
          </div>
          <Field
            label={form.type === 'xodim' ? 'Lavozim / kafedra' : form.type === 'talaba' ? 'Guruh va kurs' : 'Guruh / Lavozim'}
            required
            error={errors.groupOrPosition}
            hint={form.type === 'talaba' ? 'Masalan: «2-kurs, DI-2301»' : undefined}
          >
            <Input
              placeholder={form.type === 'xodim' ? "O'qituvchi, Anatomiya" : '2-kurs, DI-2301'}
              value={form.groupOrPosition}
              onChange={(e) => set('groupOrPosition', e.target.value)}
            />
          </Field>
          {form.type && (
            <ParentNotifyFields
              isStudent={form.type === 'talaba'}
              value={{ parentPhone: form.parentPhone, parentNotifyEnabled: form.parentNotifyEnabled, cardNumber: form.cardNumber }}
              onChange={(next) => setForm((f) => ({ ...f, ...next }))}
              errors={{ parentPhone: errors.parentPhone }}
            />
          )}

          {similar && similar.length > 0 && (
            <div role="alert" className="rounded-card border border-warning/30 bg-warning-soft p-3.5">
              <p className="text-sm font-semibold text-fg">Bu odam bazada allaqachon bo&apos;lishi mumkin</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">
                Ro&apos;yxatdagi odamni qayta qo&apos;shsangiz, u ikki marta sanaladi. O&apos;zi bo&apos;lsa — yuzni mavjud yozuvga biriktiring.
              </p>
              <ul className="mt-2.5 flex max-h-56 flex-col gap-1.5 overflow-y-auto">
                {similar.map((person) => (
                  <li key={person.id} className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border bg-surface px-3 py-2">
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-fg">{person.fullName}</span>
                      <span className="block text-xs text-muted">
                        {[person.faculty, person.groupOrPosition].filter(Boolean).join(' · ')} ·{' '}
                        {person.biometricsStatus === 'tasdiqlangan' ? 'yuzi tasdiqlangan' : 'yuzi tasdiqlanmagan'}
                      </span>
                    </span>
                    <Button size="sm" variant="primary" onClick={() => chooseExisting(person)}>
                      Shu odamga yuz biriktirish
                    </Button>
                  </li>
                ))}
              </ul>
              <Button size="sm" variant="ghost" onClick={confirmNewPerson} className="-ml-2 mt-2">
                Bu boshqa odam — yangi yozuv yaratish
              </Button>
            </div>
          )}
        </form>
      )}

      {step > 1 && existing && (
        <p className="mb-3 rounded-control bg-primary-soft px-3 py-2 text-xs text-fg">
          Yangi yozuv yaratilmaydi — yuz mavjud yozuvga biriktiriladi: <span className="font-semibold">{existing.fullName}</span> (
          {existing.groupOrPosition})
          {existing.biometricsStatus === 'tasdiqlangan' && ' · yuz rasmi almashtiriladi'}
          {(form.parentPhone || form.cardNumber || form.parentNotifyEnabled) &&
            ". Ota-ona va karta ma'lumotlari tahrirlash oynasida"}
        </p>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-4">
          <p className="text-center text-[13px] text-muted">{form.fullName} uchun pasport nusxasini (PDF) yuklang — rasm avtomatik ajratib olinadi</p>
          <PassportUploadStep
            onLoaded={(url, name) => {
              setPassportPhoto(url);
              setPassportFileName(name);
            }}
          />
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <p className="text-center text-[13px] text-muted">Endi kamera orqali jonli yuzni suratga oling</p>
          <FaceCapture
            onConfirm={(dataUrl) => {
              setCapturedFace(dataUrl);
              setMatchResult(null);
              setStep(4);
            }}
          />
        </div>
      )}

      {step === 4 && passportPhoto && capturedFace && (
        <div className="flex flex-col gap-4">
          <FaceMatchStep
            passportPhotoUrl={passportPhoto}
            capturedFaceUrl={capturedFace}
            onRetake={() => setStep(3)}
            onResult={(score, passed) => setMatchResult({ score, passed })}
          />
          {passportFileName && <p className="text-center text-xs text-muted">Pasport fayli: {passportFileName}</p>}
          {saveError && <ErrorState title="Saqlab bo'lmadi" message={saveError} />}
        </div>
      )}
    </Modal>
      <ConfirmDialog
        open={confirmDiscard}
        title="Qo'shishni to'xtatasizmi?"
        message="Ma'lumot, pasport nusxasi va yuz surati saqlanmaydi."
        confirmLabel="Ha, to'xtatilsin"
        cancelLabel="Davom ettirish"
        onCancel={() => setConfirmDiscard(false)}
        onConfirm={handleClose}
      />
    </>
  );
}
