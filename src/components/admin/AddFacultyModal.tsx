import { useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField } from '../FormField';
import { required, numberRange } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Faculty } from '../../types';

export default function AddFacultyModal({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (faculty: Faculty) => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState('');
  const [courseCount, setCourseCount] = useState('6');
  const [errors, setErrors] = useState<{ name?: string; courseCount?: string; form?: string }>({});
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next = {
      name: required(name, 'Fakultet nomi kiritilishi shart'),
      courseCount: numberRange(courseCount, 1, 8, "1 dan 8 gacha bo'lgan qiymat kiriting"),
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;

    setSubmitting(true);
    try {
      const faculty = await api.post<Faculty>(
        '/api/faculties',
        { name: name.trim(), courseCount: Number(courseCount) },
        token,
      );
      onAdd(faculty);
      setName('');
      setCourseCount('6');
      setErrors({});
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Yangi fakultet qo'shish" maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}
        <TextField
          label="Fakultet nomi"
          placeholder="Stomatologiya"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <TextField
          label="Kurslar soni"
          type="number"
          min={1}
          max={8}
          value={courseCount}
          onChange={(e) => setCourseCount(e.target.value)}
          error={errors.courseCount}
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
