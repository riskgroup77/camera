import { useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { TextField } from '../FormField';
import { required } from '../../lib/validation';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Building, Department } from '../../types';

/**
 * Yangi kafedra qo'shish.
 *
 * Bino ixtiyoriy, lekin kuchli tavsiya etiladi: monitoring sahifasidagi
 * filtr bino -> kafedra tartibida kaskadli ishlaydi, ya'ni binosi
 * ko'rsatilmagan kafedra bino tanlangach ro'yxatdan yo'qoladi. Shu sabab
 * maydon "ixtiyoriy" deb emas, izoh bilan ko'rsatiladi.
 */
export default function AddDepartmentModal({
  open,
  buildings,
  onClose,
  onAdd,
}: {
  open: boolean;
  buildings: Building[];
  onClose: () => void;
  onAdd: (department: Department) => void;
}) {
  const { token } = useAuth();
  const [name, setName] = useState('');
  const [buildingId, setBuildingId] = useState('');
  const [errors, setErrors] = useState<{ name?: string; form?: string }>({});
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const next = { name: required(name, 'Kafedra nomi kiritilishi shart') };
    setErrors(next);
    if (next.name) return;

    setSubmitting(true);
    try {
      const department = await api.post<Department>(
        '/api/departments',
        { name: name.trim(), buildingId: buildingId || null },
        token,
      );
      onAdd(department);
      setName('');
      setBuildingId('');
      setErrors({});
      onClose();
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi" });
    } finally {
      setSubmitting(false);
    }
  }

  const selectClass =
    'w-full rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 text-sm text-slate-900 outline-none transition-colors focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100';

  return (
    <Modal open={open} onClose={onClose} title="Yangi kafedra qo'shish" maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {errors.form && (
          <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {errors.form}
          </p>
        )}
        <TextField
          label="Kafedra nomi"
          placeholder="Anatomiya kafedrasi"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-400">
            Qaysi binoda
          </label>
          <select value={buildingId} onChange={(e) => setBuildingId(e.target.value)} className={selectClass}>
            <option value="">Ko&apos;rsatilmagan</option>
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
            Monitoring sahifasidagi filtr avval bino, keyin kafedra bo&apos;yicha ishlaydi — binosi
            ko&apos;rsatilmagan kafedra bino tanlangach ro&apos;yxatda ko&apos;rinmaydi.
          </p>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-glass">
            Bekor qilish
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Saqlanmoqda...' : "Qo'shish"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
