import { useEffect, useState, type FormEvent } from 'react';
import Modal from '../Modal';
import { SelectField } from '../FormField';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AIModule } from '../../types';

interface FormState {
  threshold: string;
  sensitivity: AIModule['sensitivity'];
  active: boolean;
}

function toForm(m: AIModule): FormState {
  return {
    threshold: String(m.threshold),
    sensitivity: m.sensitivity,
    active: m.active,
  };
}

export default function AiModuleModal({
  open,
  onClose,
  module,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  module: AIModule | null;
  onSave: (module: AIModule) => void;
}) {
  const { token } = useAuth();
  const [form, setForm] = useState<FormState | null>(module ? toForm(module) : null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && module) {
      setForm(toForm(module));
      setError(null);
    }
  }, [open, module]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!module || !form) return;

    setSaving(true);
    setError(null);
    try {
      const saved = await api.patch<AIModule>(
        `/api/ai-modules/${module.id}`,
        { threshold: Number(form.threshold), sensitivity: form.sensitivity, active: form.active },
        token,
      );
      onSave(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tarmoq xatosi — backend bilan bog'lanib bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Modulni sozlash" maxWidth="max-w-md">
      {form && module && (
        <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
          <div className="glass-deep space-y-1 p-4">
            <p className="text-sm font-bold text-slate-900 dark:text-slate-100">{module.name}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{module.description}</p>
            <p className="text-[11px] text-slate-400 dark:text-slate-500">{module.method}</p>
          </div>

          {error && (
            <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
              {error}
            </p>
          )}

          <div>
            <label className="mb-1.5 flex items-center justify-between text-xs font-semibold text-slate-600 dark:text-slate-400">
              <span>Threshold</span>
              <span className="font-mono text-indigo-600">{form.threshold}%</span>
            </label>
            <input
              type="range"
              min={0}
              max={100}
              value={form.threshold}
              onChange={(e) => set('threshold', e.target.value)}
              className="w-full accent-indigo-600"
            />
          </div>

          <SelectField
            label="Sezgirlik"
            value={form.sensitivity}
            onChange={(e) => set('sensitivity', e.target.value as AIModule['sensitivity'])}
            options={[
              { value: 'past', label: 'Past' },
              { value: "o'rta", label: "O'rta" },
              { value: 'yuqori', label: 'Yuqori' },
            ]}
          />

          <label
            className={`flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-400 ${
              !module.hasDetector ? 'opacity-50' : ''
            }`}
          >
            <input
              type="checkbox"
              checked={form.active}
              disabled={!module.hasDetector}
              onChange={(e) => set('active', e.target.checked)}
              className="rounded border-slate-300 dark:border-white/10"
            />
            Modul faol
          </label>
          {!module.hasDetector && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500">
              Bu modul uchun hali aniqlash logikasi yozilmagan — faollashtirib bo'lmaydi.
            </p>
          )}

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
