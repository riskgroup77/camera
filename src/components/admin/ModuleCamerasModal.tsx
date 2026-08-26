import { useCallback, useEffect, useState } from 'react';
import { Loader2, Video } from 'lucide-react';
import Modal from '../Modal';
import Badge from '../Badge';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AIModule, ModuleCameraAssignments } from '../../types';

const STATUS_LABEL = { faol: 'Faol', nofaol: 'Nofaol', tamirda: "Ta'mirda" } as const;

export default function ModuleCamerasModal({
  open,
  module,
  onClose,
  onSaved,
}: {
  open: boolean;
  module: AIModule | null;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const { token } = useAuth();
  const [data, setData] = useState<ModuleCameraAssignments | null>(null);
  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    if (!module || !token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<ModuleCameraAssignments>(
        `/api/cameras/by-module/${module.code}/assignments`,
        token,
      );
      setData(res);
      setPending(new Map());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Yuklab bo‘lmadi');
    } finally {
      setLoading(false);
    }
  }, [module, token]);

  useEffect(() => {
    if (open && module) load();
  }, [open, module, load]);

  function isEnabled(cameraId: string, original: boolean): boolean {
    return pending.has(cameraId) ? pending.get(cameraId)! : original;
  }

  function toggle(cameraId: string, original: boolean) {
    const current = isEnabled(cameraId, original);
    setPending((prev) => {
      const next = new Map(prev);
      const newVal = !current;
      if (newVal === original) next.delete(cameraId);
      else next.set(cameraId, newVal);
      return next;
    });
  }

  function setAll(enabled: boolean) {
    if (!data) return;
    const next = new Map<string, boolean>();
    for (const c of data.cameras) {
      if (c.enabled !== enabled) next.set(c.cameraId, enabled);
    }
    setPending(next);
  }

  async function handleSave() {
    if (!module || pending.size === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const assignments = Array.from(pending.entries()).map(([cameraId, enabled]) => ({
        cameraId,
        enabled,
      }));
      await api.patch<ModuleCameraAssignments>(
        `/api/cameras/by-module/${module.code}/assignments`,
        { assignments },
        token,
      );
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Saqlab bo‘lmadi');
    } finally {
      setSaving(false);
    }
  }

  const cameras = (data?.cameras ?? []).filter((c) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return (
      c.cameraName.toLowerCase().includes(q) ||
      c.building.toLowerCase().includes(q) ||
      c.zone.toLowerCase().includes(q)
    );
  });

  const enabledCount = data
    ? data.cameras.filter((c) => isEnabled(c.cameraId, c.enabled)).length
    : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={module ? `#${module.code} — ${module.name}` : ''}
      maxWidth="max-w-2xl"
    >
      {module && (
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Qaysi kameralarda bu AI kriteriyasi ishlashi kerakligini belgilang. O‘chirilgan kamera bu modulni
            hisoblamaydi — tezroq aylanish va kamroq yuk.
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              placeholder="Kamera, bino yoki zona bo‘yicha qidirish..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="min-w-[200px] flex-1 rounded-lg border border-white/80 bg-white/60 px-3 py-1.5 text-sm dark:border-white/10 dark:bg-white/5"
            />
            <button type="button" onClick={() => setAll(true)} className="btn-glass text-xs">
              Hammasini yoqish
            </button>
            <button type="button" onClick={() => setAll(false)} className="btn-glass text-xs">
              Hammasini o‘chirish
            </button>
          </div>

          {loading ? (
            <div className="flex justify-center py-10 text-slate-400">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : (
            <>
              <p className="text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                {enabledCount} / {data?.cameras.length ?? 0} kamera yoqilgan
                {pending.size > 0 ? ` · ${pending.size} ta o‘zgarish` : ''}
              </p>
              <div className="max-h-80 overflow-y-auto rounded-xl border border-white/70 dark:border-white/10">
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 bg-white/90 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/90">
                    <tr>
                      <th className="px-3 py-2 w-10" />
                      <th className="px-3 py-2">Kamera</th>
                      <th className="px-3 py-2">Bino / Zona</th>
                      <th className="px-3 py-2">Holat</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/60 dark:divide-white/5">
                    {cameras.map((c) => {
                      const on = isEnabled(c.cameraId, c.enabled);
                      return (
                        <tr key={c.cameraId} className="hover:bg-white/40 dark:hover:bg-white/5">
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggle(c.cameraId, c.enabled)}
                              className="h-4 w-4 rounded border-slate-300 text-indigo-600"
                            />
                          </td>
                          <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-200">
                            <span className="flex items-center gap-1.5">
                              <Video size={14} className="text-slate-400" />
                              {c.cameraName}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-500">
                            {c.building} · {c.zone}
                          </td>
                          <td className="px-3 py-2">
                            <Badge tone={c.status === 'faol' ? 'green' : c.status === 'tamirda' ? 'amber' : 'slate'}>
                              {STATUS_LABEL[c.status]}
                            </Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {cameras.length === 0 && (
                  <p className="p-6 text-center text-sm text-slate-400">Kamera topilmadi</p>
                )}
              </div>
            </>
          )}

          {error && (
            <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-glass">
              Bekor qilish
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || loading}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Saqlanmoqda...' : pending.size ? 'Saqlash' : 'Yopish'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
