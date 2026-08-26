import { useEffect, useMemo, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import Modal from '../Modal';
import AIModuleChecklist from './AIModuleChecklist';
import { ApiError, api } from '../../lib/apiClient';
import {
  countEnabledModulesOnCamera,
  MODULE_PRESETS,
  presetExcludedCodes,
  toggleGroupExclusion,
} from '../../lib/cameraModules';
import { useAuth } from '../../lib/auth';
import { useCameraModuleOptions } from '../../lib/useCameraModuleOptions';
import type { AIModuleGroup, CameraConfig } from '../../types';

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
  const { modules, loading: modulesLoading } = useCameraModuleOptions();
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setExcluded(new Set(camera?.excludedModuleCodes ?? []));
      setError(null);
    }
  }, [open, camera]);

  const stats = useMemo(
    () => (camera ? countEnabledModulesOnCamera(modules, { excludedModuleCodes: Array.from(excluded) }) : null),
    [camera, modules, excluded],
  );

  const allCodes = useMemo(() => modules.map((m) => m.code), [modules]);

  function toggle(code: number) {
    const mod = modules.find((m) => m.code === code);
    if (!mod?.hasDetector) return;
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function applyPreset(presetId: (typeof MODULE_PRESETS)[number]['id']) {
    setExcluded(presetExcludedCodes(presetId, allCodes));
  }

  function handleToggleGroup(group: AIModuleGroup, enable: boolean) {
    setExcluded((prev) => toggleGroupExclusion(prev, group, enable, modules));
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
    <Modal open={open} onClose={onClose} title={camera ? `AI modullar — ${camera.name}` : ''} maxWidth="max-w-xl">
      {camera && (
        <div className="space-y-4">
          <div className="glass-deep space-y-2 p-3 text-xs text-slate-500 dark:text-slate-400">
            <p>
              Belgilangan modullar shu kamerada ishlaydi. Belgini olib tashlasangiz, AI kriteriyasi shu kameraga
              tegishli bo‘lmaydi — server yuki kamayadi.
            </p>
            {stats && (
              <p className="font-semibold text-indigo-600 dark:text-indigo-400">
                {stats.enabled} / {stats.runnable} ishlaydigan modul yoqilgan
                {excluded.size > 0 ? ` · ${excluded.size} ta maxsus o‘chirilgan` : ' · standart (hammasi)'}
              </p>
            )}
          </div>

          <div>
            <p className="mb-1.5 flex items-center gap-1 text-[11px] font-bold uppercase tracking-wide text-slate-400">
              <Sparkles size={12} />
              Shablonlar
            </p>
            <div className="flex flex-wrap gap-1.5">
              {MODULE_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  title={p.description}
                  onClick={() => applyPreset(p.id)}
                  className="rounded-lg bg-white/70 px-2.5 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-indigo-50 hover:text-indigo-700 dark:bg-white/5 dark:text-slate-400 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {modulesLoading ? (
            <div className="flex items-center justify-center py-8 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : (
            <AIModuleChecklist
              modules={modules}
              excluded={excluded}
              onToggle={toggle}
              onToggleGroup={handleToggleGroup}
            />
          )}

          {error && (
            <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 border-t border-white/60 pt-3 dark:border-white/10">
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
