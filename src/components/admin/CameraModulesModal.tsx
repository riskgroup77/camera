import { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import Modal from '../Modal';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useAiModules } from '../../lib/useAiModules';
import { AI_MODULE_GROUP_LABELS } from '../../mock/admin';
import type { AIModule, AIModuleGroup, CameraConfig } from '../../types';

const GROUPS = Object.keys(AI_MODULE_GROUP_LABELS) as AIModuleGroup[];

/** Har bir belgi (checkbox) — "shu modul shu kamerada ISHLASIN" ma'nosida
 * ko'rsatiladi (intuitiv, admin uchun tabiiyroq), garchi backendda buning
 * teskarisi — excludedModuleCodes (chetlashtirilganlar ro'yxati) — saqlansa
 * ham. Belgi olib tashlanganda kod excludedModuleCodes'ga qo'shiladi. */
export default function CameraModulesModal({
  open,
  camera,
  onClose,
  onSave,
}: {
  open: boolean;
  camera: CameraConfig | null;
  onClose: () => void;
  onSave: (camera: CameraConfig) => void;
}) {
  const { token } = useAuth();
  const { modules, loading: modulesLoading } = useAiModules();
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setExcluded(new Set(camera?.excludedModuleCodes ?? []));
      setError(null);
    }
  }, [open, camera]);

  const byGroup = useMemo(() => {
    const map = new Map<AIModuleGroup, AIModule[]>();
    for (const g of GROUPS) map.set(g, []);
    for (const m of modules) map.get(m.group)?.push(m);
    return map;
  }, [modules]);

  function toggle(code: number) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function handleSave() {
    if (!camera) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.patch<CameraConfig>(
        `/api/cameras/${camera.id}/modules`,
        { excludedModuleCodes: excluded.size > 0 ? Array.from(excluded) : null },
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
    <Modal open={open} onClose={onClose} title={camera ? `AI modullar — ${camera.name}` : ''} maxWidth="max-w-lg">
      {camera && (
        <div className="space-y-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Belgilangan modullar shu kamerada ishlaydi. Belgini olib tashlasangiz, o'sha AI kriteriyasi shu kameraga
            umuman tegishli bo'lmaydi (masalan, ichki auditoriya kamerasida transport aniqlashning keragi yo'q) —
            server tomondagi hisoblash yukini kamaytiradi.
          </p>

          {modulesLoading ? (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : (
            <div className="max-h-96 space-y-4 overflow-y-auto pr-1">
              {GROUPS.map((group) => {
                const groupModules = byGroup.get(group) ?? [];
                if (groupModules.length === 0) return null;
                return (
                  <div key={group}>
                    <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                      {AI_MODULE_GROUP_LABELS[group]}
                    </p>
                    <div className="space-y-1">
                      {groupModules.map((m) => (
                        <label
                          key={m.code}
                          className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-white/60 dark:hover:bg-white/5"
                        >
                          <input
                            type="checkbox"
                            checked={!excluded.has(m.code)}
                            onChange={() => toggle(m.code)}
                            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className={excluded.has(m.code) ? 'text-slate-400 dark:text-slate-500' : 'text-slate-700 dark:text-slate-300'}>
                            #{m.code} {m.name}
                          </span>
                          {!m.active && (
                            <span className="ml-auto text-[10px] font-semibold text-slate-400 dark:text-slate-500">
                              (o'chirilgan)
                            </span>
                          )}
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
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
              disabled={saving || modulesLoading}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-btn transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? 'Saqlanmoqda...' : 'Saqlash'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
