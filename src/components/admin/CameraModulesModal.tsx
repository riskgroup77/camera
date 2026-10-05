import { useEffect, useMemo, useState } from 'react';
import { Sparkles } from 'lucide-react';
import AIModuleChecklist from './AIModuleChecklist';
import { Notice } from '../settings/kit';
import { Button, Modal, SkeletonText } from '../../ui';
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
      setError(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open && !!camera}
      onClose={onClose}
      title="AI modullar"
      description={camera?.name}
      size="lg"
      dismissible={!saving}
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Bekor qilish
          </Button>
          <Button variant="primary" onClick={handleSave} loading={saving} disabled={modulesLoading}>
            Saqlash
          </Button>
        </>
      }
    >
      {camera && (
        <div className="flex flex-col gap-4">
          <Notice
            tone={excluded.size > 0 ? 'warning' : 'info'}
            title={
              stats
                ? `${stats.enabled} / ${stats.runnable} ishlaydigan modul yoqilgan` +
                  (excluded.size > 0 ? ` · ${excluded.size} ta maxsus o‘chirilgan` : ' · standart (hammasi)')
                : undefined
            }
          >
            Belgilangan modullar shu kamerada ishlaydi. Belgini olib tashlasangiz, AI kriteriyasi shu kameraga tegishli
            bo‘lmaydi — server yuki kamayadi.
          </Notice>

          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold uppercase tracking-wide text-muted">
              <Sparkles size={13} aria-hidden="true" />
              Shablonlar
            </p>
            <div className="flex flex-wrap gap-1.5">
              {MODULE_PRESETS.map((p) => (
                <Button key={p.id} size="sm" variant="secondary" title={p.description} onClick={() => applyPreset(p.id)}>
                  {p.label}
                </Button>
              ))}
            </div>
          </div>

          {modulesLoading ? (
            <SkeletonText lines={6} />
          ) : (
            <AIModuleChecklist modules={modules} excluded={excluded} onToggle={toggle} onToggleGroup={handleToggleGroup} />
          )}

          {error && <Notice tone="danger">{error}</Notice>}
        </div>
      )}
    </Modal>
  );
}
