import { Link } from 'react-router-dom';
import { Settings2, VideoOff } from 'lucide-react';
import Modal from '../Modal';
import Badge from '../Badge';
import LiveVideoPlayer from '../LiveVideoPlayer';
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
}: {
  camera: CameraConfig | null;
  onClose: () => void;
}) {
  return (
    <Modal open={!!camera} onClose={onClose} title={camera?.name} maxWidth="max-w-sm">
      {camera && (
        <div className="space-y-4">
          <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl bg-slate-900">
            {camera.status === 'faol' && (
              <LiveVideoPlayer streamUrl={camera.streamUrl} cameraId={camera.id} showDetections />
            )}
            {!camera.streamUrl && (
              <div className="flex flex-col items-center gap-1.5 text-slate-500">
                <VideoOff size={20} />
                <span className="text-[11px] font-medium">
                  {camera.status === 'faol' ? 'Video oqim ulanmagan' : STATUS_LABEL[camera.status]}
                </span>
              </div>
            )}
          </div>

          <Badge tone={STATUS_TONE[camera.status]}>{STATUS_LABEL[camera.status]}</Badge>

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

          <Link
            to="/admin/cameras"
            onClick={onClose}
            className="btn-glass flex items-center justify-center gap-1.5"
          >
            <Settings2 size={14} />
            Kameralar bo'limida sozlash
          </Link>
        </div>
      )}
    </Modal>
  );
}
