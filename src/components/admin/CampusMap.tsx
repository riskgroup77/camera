import { useEffect, useState } from 'react';
import { Building2 } from 'lucide-react';
import { api, fetchAllPages } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useBuildings } from '../../lib/useBuildings';
import CameraConfigDetailModal from './CameraConfigDetailModal';
import type { CameraConfig } from '../../types';

const STATUS_DOT: Record<CameraConfig['status'], string> = {
  faol: 'bg-emerald-500',
  nofaol: 'bg-slate-400',
  tamirda: 'bg-amber-500',
};

const STATUS_LABEL: Record<CameraConfig['status'], string> = {
  faol: 'Faol',
  nofaol: 'Nofaol',
  tamirda: "Ta'mirda",
};

export default function CampusMap() {
  const { token } = useAuth();
  const { buildings } = useBuildings();
  const [cameraConfigs, setCameraConfigs] = useState<CameraConfig[]>([]);
  const [selected, setSelected] = useState<CameraConfig | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetchAllPages<CameraConfig>('/api/cameras', token)
      .then((items) => {
        if (!cancelled) setCameraConfigs(items);
      })
      .catch(() => {
        /* ulanish muvaffaqiyatsiz — bo'sh ro'yxat bilan davom etamiz */
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {buildings.map((b) => {
          const cameras = cameraConfigs.filter((c) => c.building === b.name);

          return (
            <div key={b.id} className="glass-deep flex flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-400">
                  <Building2 size={15} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">
                    {b.name}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {cameras.length} ta kamera
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 rounded-xl bg-slate-100/60 p-3 dark:bg-white/5">
                {cameras.length === 0 ? (
                  <span className="text-xs text-slate-400">Kamera biriktirilmagan</span>
                ) : (
                  cameras.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => setSelected(c)}
                      title={`${c.name} · ${c.zone} · ${STATUS_LABEL[c.status]}`}
                      className={`h-3.5 w-3.5 rounded-sm transition-transform hover:scale-125 ${STATUS_DOT[c.status]}`}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" />
          Faol
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-amber-500" />
          Ta'mirda
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-slate-400" />
          Nofaol
        </span>
        <span className="text-slate-400 dark:text-slate-500">(kamerani bosing — batafsil)</span>
      </div>

      <CameraConfigDetailModal camera={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
