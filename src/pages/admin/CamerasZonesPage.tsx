import { useEffect, useState } from 'react';
import { Cpu, Eye, Loader2, MapPinned, Plus, Settings2, Video, VideoOff, Wrench } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import AddCameraModal from '../../components/admin/AddCameraModal';
import CameraConfigDetailModal from '../../components/admin/CameraConfigDetailModal';
import CameraModulesModal from '../../components/admin/CameraModulesModal';
import CameraZoneModal from '../../components/admin/CameraZoneModal';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useServerPage } from '../../lib/useServerPage';
import { useBuildings } from '../../lib/useBuildings';
import { useCameraZones } from '../../lib/useCameraZones';
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

const STATUS_FILTERS = ['Barchasi', 'Faol', 'Nofaol', "Ta'mirda"] as const;
const STATUS_VALUE: Record<(typeof STATUS_FILTERS)[number], CameraConfig['status'] | undefined> = {
  Barchasi: undefined,
  Faol: 'faol',
  Nofaol: 'nofaol',
  "Ta'mirda": 'tamirda',
};

export default function CamerasZonesPage() {
  const { token } = useAuth();
  const { buildings } = useBuildings();
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>('Barchasi');
  const [buildingFilter, setBuildingFilter] = useState<string | null>(null);
  const [zoneFilter, setZoneFilter] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<CameraConfig | null>(null);
  const [viewing, setViewing] = useState<CameraConfig | null>(null);
  const [drawingZone, setDrawingZone] = useState<CameraConfig | null>(null);
  const [editingModules, setEditingModules] = useState<CameraConfig | null>(null);
  const [counts, setCounts] = useState<{ faol: number; nofaol: number; tamirda: number } | null>(null);
  const { zones } = useCameraZones(buildingFilter ?? undefined);

  const {
    items: cameras,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
    reload,
  } = useServerPage<CameraConfig>(
    '/api/cameras',
    { status: STATUS_VALUE[statusFilter], building: buildingFilter ?? undefined, zone: zoneFilter ?? undefined },
    10,
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all(
      (['faol', 'nofaol', 'tamirda'] as const).map((s) =>
        api.get<{ total: number }>(`/api/cameras?status=${s}&pageSize=1`, token),
      ),
    ).then(([faol, nofaol, tamirda]) => {
      if (cancelled) return;
      setCounts({ faol: faol.total, nofaol: nofaol.total, tamirda: tamirda.total });
    });
    return () => {
      cancelled = true;
    };
  }, [token, cameras]);

  return (
    <section className="glass p-6">
      <PageHeader
        title="Kameralar va Zonalar"
        subtitle="RTSP kamera konfiguratsiyasi va zona boshqaruvi"
        action={
          <button
            onClick={() => setAddOpen(true)}
            className="btn-glass flex items-center gap-1.5 !bg-indigo-600 !text-white hover:!bg-indigo-700"
          >
            <Plus size={14} />
            Yangi kamera qo'shish
          </button>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard icon={<Video size={20} />} value={counts?.faol ?? '—'} label="Faol kameralar" tone="green" />
        <StatCard icon={<VideoOff size={20} />} value={counts?.nofaol ?? '—'} label="Nofaol kameralar" tone="slate" />
        <StatCard icon={<Wrench size={20} />} value={counts?.tamirda ?? '—'} label="Ta'mirda" tone="amber" />
      </div>

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              statusFilter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
            }`}
          >
            {f}
          </button>
        ))}
        <span className="mx-1 w-px self-stretch bg-white/80 dark:bg-white/10" />
        {buildings.map((b) => (
          <button
            key={b.id}
            onClick={() => {
              setBuildingFilter((cur) => (cur === b.name ? null : b.name));
              setZoneFilter(null);
            }}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              buildingFilter === b.name ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
            }`}
          >
            {b.name}
          </button>
        ))}
      </div>

      {zones.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2 text-xs">
          <span className="flex items-center px-1 font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            Xona/Zona:
          </span>
          {zones.map((z) => (
            <button
              key={z.zone}
              onClick={() => setZoneFilter((cur) => (cur === z.zone ? null : z.zone))}
              className={`rounded-lg px-2.5 py-1 font-medium transition-colors ${
                zoneFilter === z.zone
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
              }`}
            >
              {z.zone} ({z.cameraCount})
            </button>
          ))}
        </div>
      )}

      {loading && cameras.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : cameras.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
          Filtrlarga mos kamera topilmadi
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <th className="px-4 py-3">Kamera nomi</th>
                <th className="px-4 py-3">IP / RTSP</th>
                <th className="px-4 py-3">Bino</th>
                <th className="px-4 py-3">Zona</th>
                <th className="px-4 py-3">Ruxsat / FPS</th>
                <th className="px-4 py-3">Holat</th>
                <th className="px-4 py-3">Aloqa</th>
                <th className="px-4 py-3">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {cameras.map((c) => (
                <tr key={c.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">{c.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">{c.ip}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{c.building}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{c.zone}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {c.resolution} / {c.fps ? `${c.fps} fps` : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    {c.status !== 'faol' ? (
                      <span className="text-xs text-slate-400 dark:text-slate-500">—</span>
                    ) : (
                      <span
                        title={
                          c.isReachable
                            ? "Kamera oxirgi tekshiruvda topildi"
                            : "Kamera hozircha javob bermayapti — kabel/tarmoq muammosi bo'lishi mumkin"
                        }
                        className={`flex items-center gap-1.5 text-xs font-semibold ${
                          c.isReachable
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-red-500 dark:text-red-400'
                        }`}
                      >
                        <span
                          className={`h-2 w-2 rounded-full ${
                            c.isReachable ? 'bg-emerald-500' : 'bg-red-500'
                          }`}
                        />
                        {c.isReachable ? 'Ulangan' : "Javob yo'q"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setViewing(c)}
                        className="flex items-center gap-1 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                      >
                        <Eye size={12} />
                        Ko'rish
                      </button>
                      <button
                        onClick={() => setEditing(c)}
                        className="flex items-center gap-1 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                      >
                        <Settings2 size={12} />
                        Sozlash
                      </button>
                      <button
                        onClick={() => setDrawingZone(c)}
                        title="Taqiqlangan zonani belgilash"
                        className={`flex items-center gap-1 text-xs font-semibold hover:underline ${
                          c.restrictedZonePolygon && c.restrictedZonePolygon.length > 0
                            ? 'text-red-600 dark:text-red-400'
                            : 'text-indigo-600 dark:text-indigo-400'
                        }`}
                      >
                        <MapPinned size={12} />
                        Zona
                      </button>
                      <button
                        onClick={() => setEditingModules(c)}
                        title="AI modullarni sozlash"
                        className={`flex items-center gap-1 text-xs font-semibold hover:underline ${
                          c.excludedModuleCodes && c.excludedModuleCodes.length > 0
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-indigo-600 dark:text-indigo-400'
                        }`}
                      >
                        <Cpu size={12} />
                        Modullar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
          </div>
        </div>
      )}

      <AddCameraModal open={addOpen} onClose={() => setAddOpen(false)} onSave={() => reload()} />
      <AddCameraModal open={!!editing} camera={editing} onClose={() => setEditing(null)} onSave={() => reload()} />
      <CameraConfigDetailModal camera={viewing} onClose={() => setViewing(null)} />
      <CameraZoneModal
        open={!!drawingZone}
        camera={drawingZone}
        onClose={() => setDrawingZone(null)}
        onSave={() => reload()}
      />
      <CameraModulesModal
        open={!!editingModules}
        camera={editingModules}
        onClose={() => setEditingModules(null)}
        onSave={() => reload()}
      />
    </section>
  );
}
