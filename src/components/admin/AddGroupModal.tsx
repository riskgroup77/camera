import { useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField, SelectField } from '../FormField';
import { required, numberRange } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Faculty, StudentGroup } from '../../types';

export default function AddGroupModal({
  open,
  faculties,
  onClose,
  onAdd,
}: {
  open: boolean;
  faculties: Faculty[];
  onClose: () => void;
  onAdd: (group: StudentGroup) => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState('');
  const [facultyId, setFacultyId] = useState('');
  const [course, setCourse] = useState('1');
  const [errors, setErrors] = useState<{ name?: string; faculty?: string; course?: string; form?: string }>({});
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next = {
      name: required(name, 'Guruh nomi kiritilishi shart'),
      faculty: facultyId ? undefined : 'Fakultetni tanlang',
      course: numberRange(course, 1, 6, "1 dan 6 gacha bo'lgan qiymat kiriting"),
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSubmitting(true);
    try {
      const group = await api.post<StudentGroup>(
        '/api/student-groups',
        { name: name.trim(), facultyId, course: Number(course) },
        token,
      );
      onAdd(group);
      setName('');
      setFacultyId('');
      setCourse('1');
      setErrors({});
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Yangi guruh qo'shish" maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}
        <TextField
          label="Guruh nomi"
          placeholder="207-guruh"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <SelectField
          label="Fakultet"
          placeholder="Tanlang"
          value={facultyId}
          onChange={(e) => setFacultyId(e.target.value)}
          error={errors.faculty}
          options={faculties.map((f) => ({ value: f.id, label: f.name }))}
        />
        <TextField
          label="Kurs"
          type="number"
          min={1}
          max={6}
          value={course}
          onChange={(e) => setCourse(e.target.value)}
          error={errors.course}
        />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {submitting ? 'Qo\'shilmoqda...' : "Qo'shish"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
