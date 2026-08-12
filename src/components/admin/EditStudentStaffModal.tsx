import { useEffect, useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useFaculties } from '../../lib/useFaculties';
import type { StudentStaffRecord } from '../../types';

interface FormState {
  fullName: string;
  type: 'talaba' | 'xodim';
  faculty: string;
  groupOrPosition: string;
}

function toForm(r: StudentStaffRecord): FormState {
  return {
    fullName: r.fullName,
    type: r.type,
    faculty: r.faculty,
    groupOrPosition: r.groupOrPosition,
  };
}

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
  const [form, setForm] = useState<FormState | null>(record ? toForm(record) : null);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>> & { form?: string }>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (record) {
      setForm(toForm(record));
      setErrors({});
    }
  }, [record]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!record || !form) return;

    const next = {
      fullName: required(form.fullName, "F.I.Sh. kiritilishi shart"),
      faculty: form.faculty ? undefined : 'Fakultetni tanlang',
      groupOrPosition: required(form.groupOrPosition, 'Guruh yoki lavozim kiritilishi shart'),
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSaving(true);
    try {
      const updated = await api.patch<StudentStaffRecord>(`/api/students-staff/${record.id}`, form, token);
      onSave(updated);
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={!!record} onClose={onClose} title="Ma'lumotlarni tahrirlash" maxWidth="max-w-md">
      {form && (
        <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
          {errors.form && (
            <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
              {errors.form}
            </p>
          )}
          <TextField
            label="F.I.Sh."
            value={form.fullName}
            onChange={(e) => set('fullName', e.target.value)}
            error={errors.fullName}
          />
          <SelectField
            label="Turi"
            value={form.type}
            onChange={(e) => set('type', e.target.value as FormState['type'])}
            options={[
              { value: 'talaba', label: 'Talaba' },
              { value: 'xodim', label: 'Xodim' },
            ]}
          />
          <SelectField
            label="Fakultet"
            value={form.faculty}
            onChange={(e) => set('faculty', e.target.value)}
            error={errors.faculty}
            options={faculties.map((f) => ({ value: f.name, label: f.name }))}
          />
          <TextField
            label="Guruh / Lavozim"
            value={form.groupOrPosition}
            onChange={(e) => set('groupOrPosition', e.target.value)}
            error={errors.groupOrPosition}
          />

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-glass">
              Bekor qilish
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {saving ? 'Saqlanmoqda...' : 'Saqlash'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
