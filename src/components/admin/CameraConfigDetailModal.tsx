import { useEffect, useState } from 'react';
import { Cpu, Eye, EyeOff } from 'lucide-react';
import Modal from '../Modal';
import Badge from '../Badge';
import LiveVideoPlayer from '../LiveVideoPlayer';
import { formatModuleSummary } from '../../lib/cameraModules';
import { useCameraModuleOptions } from '../../lib/useCameraModuleOptions';
import type { CameraConfig } from '../../types';

const STATUS_TONE: Record<CameraConfig['status'], 'green' | 'slate' | 'amber'> = {
  faol: 'green',
  nofaol: 'slate',
  tamirda: 'amber',
};

const STATUS_LABEL: Record<CameraConfig['status'], string> = {
  faol: 'Faol',
  nofaol: 'Nofaol',
  tamirda: "Ta'mirda",
};

export default function CameraConfigDetailModal({
  camera,
  onClose,
  onEditModules,
}: {
  camera: CameraConfig | null;
  onClose: () => void;
  onEditModules?: () => void;
}) {
  const [showDetections, setShowDetections] = useState(false);
  const { modules } = useCameraModuleOptions();
  const moduleSummary = camera && modules.length > 0 ? formatModuleSummary(modules, camera) : null;

  useEffect(() => {
    setShowDetections(false);
  }, [camera?.id]);

  return (
    <Modal open={!!camera} onClose={onClose} title={camera?.name} maxWidth="max-w-md">
      {camera && (
        <div className="space-y-4">
          <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl bg-slate-900">
            {camera.status === 'faol' && (
              <LiveVideoPlayer
                streamUrl={camera.streamUrl}
                cameraId={camera.id}
                showDetections={showDetections}
              />
            )}
            {camera.status === 'faol' && camera.streamUrl && (
              <button
                type="button"
                onClick={() => setShowDetections((v) => !v)}
                className="absolute bottom-2 left-2 flex items-center gap-1 rounded-lg bg-black/50 px-2 py-1 text-[10px] font-semibold text-white hover:bg-black/70"
              >
                {showDetections ? <EyeOff size={12} /> : <Eye size={12} />}
                {showDetections ? 'AI o\'chirish' : 'AI ko\'rsatkich'}
              </button>
            )}
            {!camera.streamUrl && (
              <div className="flex flex-col items-center gap-1.5 text-slate-500">
                <span className="text-[11px] font-medium">
                  {camera.status === 'faol' ? 'Video oqim ulanmagan' : STATUS_LABEL[camera.status]}
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[camera.status]}>{STATUS_LABEL[camera.status]}</Badge>
            {camera.isEntrance && (
              <Badge tone="indigo">Kirish kamerasi</Badge>
            )}
            {camera.isExit && (
              <Badge tone="amber">Chiqish kamerasi</Badge>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">IP manzil</p>
              <p className="font-mono font-medium text-slate-800 dark:text-slate-200">{camera.ip}</p>
            </div>
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Bino</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">{camera.building}</p>
            </div>
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Zona</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">{camera.zone}</p>
            </div>
            <div className="glass-deep px-3 py-2.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">Ruxsat / FPS</p>
              <p className="font-medium text-slate-800 dark:text-slate-200">
                {camera.resolution} {camera.fps ? `/ ${camera.fps} fps` : ''}
              </p>
            </div>
          </div>

          <div className="glass-deep flex items-center justify-between gap-3 px-3 py-2.5">
            <div>
              <p className="text-[11px] text-slate-400 dark:text-slate-500">AI modullar</p>
              <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                {moduleSummary ?? 'Yuklanmoqda...'}
              </p>
              {(camera.excludedModuleCodes?.length ?? 0) > 0 && (
                <p className="mt-0.5 text-[10px] text-amber-600 dark:text-amber-400">
                  Maxsus sozlama — ba&apos;zi kriteriyalar o‘chirilgan
                </p>
              )}
            </div>
            {onEditModules && (
              <button
                type="button"
                onClick={onEditModules}
                className="btn-glass flex shrink-0 items-center gap-1 text-xs"
              >
                <Cpu size={14} />
                Sozlash
              </button>
            )}
          </div>

          {camera.restrictedZonePolygon && camera.restrictedZonePolygon.length > 0 && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Taqiqlangan zona belgilangan ({camera.restrictedZonePolygon.length} nuqta)
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}
