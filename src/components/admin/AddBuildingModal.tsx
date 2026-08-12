import { useEffect, useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField } from '../FormField';
import { required, minLength } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Building } from '../../types';

export default function AddBuildingModal({
  open,
  building,
  onClose,
  onSave,
}: {
  open: boolean;
  building?: Building | null;
  onClose: () => void;
  onSave: (building: Building) => void;
}) {
  const { token } = useAuth();
  const isEdit = !!building;
  const [name, setName] = useState(building?.name ?? '');
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setName(building?.name ?? '');
      setError(undefined);
    }
  }, [open, building]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const err = required(name, 'Bino nomi kiritilishi shart') ?? minLength(name, 3);
    if (err) {
      setError(err);
      return;
    }

    setSubmitting(true);
    try {
      const payload = { name: name.trim(), cameraCount: building?.cameraCount ?? 0 };
      const saved = isEdit
        ? await api.patch<Building>(`/api/buildings/${building.id}`, payload, token)
        : await api.post<Building>('/api/buildings', payload, token);
      onSave(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Korpusni tahrirlash' : "Yangi korpus qo'shish"} maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <TextField
          label="Bino nomi"
          placeholder="4-Bino (Sport majmuasi)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={error}
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
            {submitting ? 'Saqlanmoqda...' : isEdit ? 'Saqlash' : "Qo'shish"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
