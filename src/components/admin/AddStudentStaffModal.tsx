import { useState, type FormEvent } from 'react';
import { Check } from 'lucide-react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required, minLength } from '../../lib/validation';
import PassportUploadStep from './PassportUploadStep';
import FaceCapture from './FaceCapture';
import FaceMatchStep from './FaceMatchStep';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useFaculties } from '../../lib/useFaculties';
import type { StudentStaffRecord } from '../../types';

interface FormState {
  fullName: string;
  type: 'talaba' | 'xodim' | '';
  faculty: string;
  groupOrPosition: string;
}

const EMPTY_FORM: FormState = { fullName: '', type: '', faculty: '', groupOrPosition: '' };

const STEPS = ["Ma'lumotlar", 'Pasport', 'Yuz skani', 'Tekshiruv'] as const;

function Stepper({ step }: { step: number }) {
  return (
    <div className="mb-6 flex items-center">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const state = n < step ? 'done' : n === step ? 'active' : 'pending';
        return (
          <div key={label} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                  state === 'done'
                    ? 'bg-indigo-600 text-white'
                    : state === 'active'
                      ? 'bg-indigo-100 dark:bg-indigo-500/15 text-indigo-600 ring-2 ring-indigo-400'
                      : 'bg-slate-100 dark:bg-white/5 text-slate-400 dark:text-slate-500'
                }`}
              >
                {state === 'done' ? <Check size={14} /> : n}
              </div>
              <span
                className={`whitespace-nowrap text-[10px] font-semibold ${
                  state === 'pending' ? 'text-slate-400 dark:text-slate-500' : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                {label}
              </span>
            </div>
            {n < STEPS.length && (
              <div className={`mx-2 h-0.5 flex-1 ${n < step ? 'bg-indigo-600' : 'bg-slate-200 dark:bg-white/10'}`} />
            )}
          </div>
        );
      })}
    </div>
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
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [passportPhoto, setPassportPhoto] = useState<string | null>(null);
  const [passportFileName, setPassportFileName] = useState<string | null>(null);
  const [capturedFace, setCapturedFace] = useState<string | null>(null);
  const [matchResult, setMatchResult] = useState<{ score: number; passed: boolean } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
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
  }

  function handleClose() {
    resetAll();
    onClose();
  }

  function validateStep1(): boolean {
    const next: typeof errors = {
      fullName: required(form.fullName) ?? minLength(form.fullName, 5, "F.I.Sh. to'liq kiritilishi kerak"),
      type: form.type ? undefined : 'Turini tanlang',
      faculty: form.faculty ? undefined : 'Fakultetni tanlang',
      groupOrPosition: required(form.groupOrPosition, 'Guruh yoki lavozim kiritilishi shart'),
    };
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  function handleStep1Submit(e: FormEvent) {
    e.preventDefault();
    if (validateStep1()) setStep(2);
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      const record = await api.post<StudentStaffRecord>(
        '/api/students-staff',
        {
          fullName: form.fullName.trim(),
          type: form.type as 'talaba' | 'xodim',
          faculty: form.faculty,
          groupOrPosition: form.groupOrPosition.trim(),
          biometricsStatus: matchResult?.passed ? 'tasdiqlangan' : 'kutilmoqda',
        },
        token,
      );

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
      setSaveError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Yangi biriktirish" maxWidth="max-w-lg">
      <Stepper step={step} />

      {step === 1 && (
        <form onSubmit={handleStep1Submit} noValidate className="flex flex-col gap-4">
          <TextField
            label="F.I.Sh."
            placeholder="Karimova Dildora Baxtiyorovna"
            value={form.fullName}
            onChange={(e) => set('fullName', e.target.value)}
            error={errors.fullName}
          />
          <SelectField
            label="Turi"
            placeholder="Tanlang"
            value={form.type}
            onChange={(e) => set('type', e.target.value as FormState['type'])}
            error={errors.type}
            options={[
              { value: 'talaba', label: 'Talaba' },
              { value: 'xodim', label: 'Xodim' },
            ]}
          />
          <SelectField
            label="Fakultet"
            placeholder="Tanlang"
            value={form.faculty}
            onChange={(e) => set('faculty', e.target.value)}
            error={errors.faculty}
            options={faculties.map((f) => ({ value: f.name, label: f.name }))}
          />
          <TextField
            label="Guruh / Lavozim"
            placeholder={form.type === 'xodim' ? "O'qituvchi, Anatomiya" : '302-guruh, 3-kurs'}
            value={form.groupOrPosition}
            onChange={(e) => set('groupOrPosition', e.target.value)}
            error={errors.groupOrPosition}
          />

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={handleClose} className="btn-glass">
              Bekor qilish
            </button>
            <button
              type="submit"
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700"
            >
              Keyingi
            </button>
          </div>
        </form>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-4">
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">
            {form.fullName} uchun pasport nusxasini (PDF) yuklang — rasm avtomatik ajratib olinadi
          </p>
          <PassportUploadStep
            onLoaded={(url, name) => {
              setPassportPhoto(url);
              setPassportFileName(name);
            }}
          />
          <div className="flex justify-between gap-2 pt-2">
            <button type="button" onClick={() => setStep(1)} className="btn-glass">
              Orqaga
            </button>
            <button
              type="button"
              disabled={!passportPhoto}
              onClick={() => setStep(3)}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Keyingi
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">
            Endi kamera orqali jonli yuzingizni suratga oling
          </p>
          <FaceCapture
            onConfirm={(dataUrl) => {
              setCapturedFace(dataUrl);
              setMatchResult(null);
              setStep(4);
            }}
          />
          <div className="flex justify-start pt-2">
            <button type="button" onClick={() => setStep(2)} className="btn-glass">
              Orqaga
            </button>
          </div>
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

          {passportFileName && (
            <p className="text-center text-[11px] text-slate-400 dark:text-slate-500">
              Pasport fayli: {passportFileName}
            </p>
          )}

          {saveError && (
            <p className="rounded-xl bg-red-50 px-3 py-2.5 text-center text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
              {saveError}
            </p>
          )}

          <div className="flex justify-between gap-2 pt-2">
            <button type="button" onClick={() => setStep(3)} className="btn-glass">
              Orqaga
            </button>
            <div className="flex items-center gap-3">
              {matchResult && !matchResult.passed && (
                <button
                  type="button"
                  disabled={saving}
                  onClick={handleSave}
                  className="text-xs font-semibold text-slate-400 dark:text-slate-500 underline hover:text-slate-600 dark:hover:text-slate-300 disabled:cursor-not-allowed"
                >
                  Qo'lda tekshirish uchun saqlash
                </button>
              )}
              <button
                type="button"
                disabled={!matchResult?.passed || saving}
                onClick={handleSave}
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? 'Saqlanmoqda...' : 'Saqlash'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
