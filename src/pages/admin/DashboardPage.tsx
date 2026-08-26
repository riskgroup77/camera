import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, ArrowRight, Camera, GraduationCap, Loader2, Users } from 'lucide-react';
import StatCard from '../../components/StatCard';
import CampusMap from '../../components/admin/CampusMap';
import { api, buildQuery, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AIModule, StudentStaffRecord } from '../../types';

interface ResourceAlert {
  metric: string;
  level: 'warning' | 'critical';
  message: string;
}

interface SystemResources {
  cpu: number;
  ram: number;
  disk: number;
  ffmpegProcessCount: number;
  streamReaderCount: number;
  alerts: ResourceAlert[];
}

interface SystemAiStatus {
  schedulerEnabled: boolean;
  globalSweepConcurrency: number;
  gpu: {
    cudaAvailable: boolean;
    faceGpuActive: boolean;
    objectGpuActive: boolean;
    recommendation: string;
  };
  lastTick: {
    durationSeconds: number;
    modulesRan: number;
    criticalRan: number;
    standardRan: number;
    skippedOverlap: boolean;
  };
  sweepSlots: { max: number; inUse: number };
  faceInferenceGate: { max: number; inUse: number; waiting: number };
  embeddingSweepCacheTtlSeconds: number;
}

interface SystemStreamStatus {
  shardingEnabled: boolean;
  shardCount: number;
  faolCameras: number;
  registeredStreams: number;
  shards: {
    index: number;
    reachable: boolean;
    pathCount: number;
    assignedCameras: number;
  }[];
  recommendation: string;
}

interface SystemCameraNetwork {
  faolCameras: number;
  reachableCameras: number;
  offlineCameras: number;
  linkLocalIpCount: number;
  chronicOfflineCount: number;
  recentOfflineAlerts24h: number;
  lastSweep: {
    durationSeconds: number;
    reachable: number;
    faolChecked: number;
    skippedOverlap: boolean;
  };
  recommendation: string;
}

function ResourceBar({ label, value }: { label: string; value: number }) {
  const tone = value > 80 ? 'bg-red-500' : value > 60 ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs font-medium text-slate-600 dark:text-slate-400">
        <span>{label}</span>
        <span>{value}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200/70 dark:bg-white/10">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { token } = useAuth();
  const [counts, setCounts] = useState<{ students: number; staff: number; activeCameras: number; todayEvents: number } | null>(
    null,
  );
  const [aiModules, setAiModules] = useState<AIModule[]>([]);
  const [resources, setResources] = useState<SystemResources | null>(null);
  const [aiStatus, setAiStatus] = useState<SystemAiStatus | null>(null);
  const [streamStatus, setStreamStatus] = useState<SystemStreamStatus | null>(null);
  const [cameraNetwork, setCameraNetwork] = useState<SystemCameraNetwork | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    Promise.all([
      api.get<Page<StudentStaffRecord>>(`/api/students-staff${buildQuery({ type: 'talaba', pageSize: 1 })}`, token),
      api.get<Page<StudentStaffRecord>>(`/api/students-staff${buildQuery({ type: 'xodim', pageSize: 1 })}`, token),
      api.get<Page<unknown>>(`/api/cameras${buildQuery({ status: 'faol', pageSize: 1 })}`, token),
      api.get<Page<unknown>>(`/api/events${buildQuery({ today: 'true', pageSize: 1 })}`, token),
    ]).then(([students, staff, activeCameras, todayEvents]) => {
      if (cancelled) return;
      setCounts({
        students: students.total,
        staff: staff.total,
        activeCameras: activeCameras.total,
        todayEvents: todayEvents.total,
      });
    });

    api.get<AIModule[]>('/api/ai-modules', token).then((res) => {
      if (!cancelled) setAiModules(res);
    });

    api.get<SystemResources>('/api/system/resources', token).then((res) => {
      if (!cancelled) setResources(res);
    });

    api.get<SystemAiStatus>('/api/system/ai-status', token).then((res) => {
      if (!cancelled) setAiStatus(res);
    });

    api.get<SystemStreamStatus>('/api/system/stream-status', token).then((res) => {
      if (!cancelled) setStreamStatus(res);
    });

    api.get<SystemCameraNetwork>('/api/system/camera-network', token).then((res) => {
      if (!cancelled) setCameraNetwork(res);
    });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const activeModules = aiModules.filter((m) => m.active);
  const topModules = activeModules.slice(0, 5);

  return (
    <div className="space-y-4">
      <section className="glass p-6">
        <h2 className="mb-1 text-lg font-extrabold text-slate-900 dark:text-slate-100">
          Boshqaruv paneli
        </h2>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Tizim holati va umumiy statistika
        </p>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={<GraduationCap size={20} />}
            value={counts ? counts.students.toLocaleString('ru-RU') : '—'}
            label="Jami talabalar"
            tone="indigo"
          />
          <StatCard
            icon={<Users size={20} />}
            value={counts ? counts.staff.toLocaleString('ru-RU') : '—'}
            label="Xodimlar"
            tone="green"
          />
          <StatCard
            icon={<Camera size={20} />}
            value={counts ? counts.activeCameras.toLocaleString('ru-RU') : '—'}
            label="Faol kameralar"
            tone="amber"
          />
          <StatCard
            icon={<Activity size={20} />}
            value={counts ? counts.todayEvents.toLocaleString('ru-RU') : '—'}
            label="Bugungi voqealar"
            tone="red"
          />
        </div>
      </section>

      <section className="glass p-6">
        <h3 className="mb-1 text-base font-bold text-slate-900 dark:text-slate-100">
          Institut plani — kameralar holati
        </h3>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Har bir bino bo'yicha biriktirilgan kameralar va ularning joriy holati
        </p>
        <CampusMap />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="glass p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
              AI Modullar holati
            </h3>
            <span className="text-xs text-slate-400 dark:text-slate-500">
              {activeModules.length} / {aiModules.length} faol
            </span>
          </div>
          {aiModules.length === 0 ? (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : (
            <div className="space-y-3">
              {topModules.map((m) => (
                <div key={m.id} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      {m.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
                      Faol
                    </span>
                    <span className="w-12 text-right text-sm font-bold text-slate-900 dark:text-slate-100">
                      {m.accuracy}%
                    </span>
                  </div>
                </div>
              ))}
              {topModules.length === 0 && (
                <p className="text-center text-xs text-slate-400 dark:text-slate-500">
                  Hozircha faol AI modul yo'q
                </p>
              )}
            </div>
          )}
          <Link
            to="/admin/ai-modules"
            className="mt-4 flex items-center justify-center gap-1.5 rounded-xl bg-white/50 py-2 text-xs font-semibold text-indigo-600 transition-colors hover:bg-white/80 dark:bg-white/5 dark:text-indigo-400 dark:hover:bg-white/10"
          >
            Barcha {aiModules.length || 25} ta modulni ko'rish
            <ArrowRight size={13} />
          </Link>
        </section>

        <section className="glass p-6">
          <h3 className="mb-4 text-base font-bold text-slate-900 dark:text-slate-100">
            Server resurslari
          </h3>
          {resources ? (
            <div className="space-y-4">
              <ResourceBar label="CPU" value={resources.cpu} />
              <ResourceBar label="RAM" value={resources.ram} />
              <ResourceBar label="Disk" value={resources.disk} />
              <div className="grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span>ffmpeg: {resources.ffmpegProcessCount}</span>
                <span>Stream o'quvchilar: {resources.streamReaderCount}</span>
              </div>
              {resources.alerts.length > 0 && (
                <ul className="space-y-1.5">
                  {resources.alerts.map((a) => (
                    <li
                      key={`${a.metric}-${a.message}`}
                      className={`rounded-lg px-2.5 py-1.5 text-xs font-medium ${
                        a.level === 'critical'
                          ? 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-400'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400'
                      }`}
                    >
                      {a.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
        </section>

        <section className="glass p-6">
          <h3 className="mb-4 text-base font-bold text-slate-900 dark:text-slate-100">
            AI infratuzilma
          </h3>
          {aiStatus ? (
            <div className="space-y-3 text-xs text-slate-600 dark:text-slate-400">
              <div className="flex flex-wrap gap-2">
                <span
                  className={`rounded-full px-2.5 py-1 font-semibold ${
                    aiStatus.gpu.faceGpuActive || aiStatus.gpu.objectGpuActive
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400'
                      : 'bg-slate-100 text-slate-600 dark:bg-white/10 dark:text-slate-400'
                  }`}
                >
                  GPU: {aiStatus.gpu.cudaAvailable ? (aiStatus.gpu.faceGpuActive ? 'CUDA faol' : 'mavjud, CPU') : 'yo\'q'}
                </span>
                <span className="rounded-full bg-indigo-100 px-2.5 py-1 font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-400">
                  Scheduler: {aiStatus.schedulerEnabled ? 'parallel' : 'loop'}
                </span>
                <span className="rounded-full bg-white/60 px-2.5 py-1 font-semibold dark:bg-white/10">
                  Sweep cap: {aiStatus.sweepSlots.inUse}/{aiStatus.sweepSlots.max}
                </span>
              </div>
              <p>
                Oxirgi tick: {aiStatus.lastTick.modulesRan} modul ({aiStatus.lastTick.criticalRan} critical,{' '}
                {aiStatus.lastTick.standardRan} standard) — {aiStatus.lastTick.durationSeconds}s
                {aiStatus.lastTick.skippedOverlap ? ' (overlap skip)' : ''}
              </p>
              <p>
                Inference: {aiStatus.faceInferenceGate.inUse}/{aiStatus.faceInferenceGate.max}
                {aiStatus.faceInferenceGate.waiting > 0 ? ` (${aiStatus.faceInferenceGate.waiting} navbatda)` : ''}
              </p>
              <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-500">
                {aiStatus.gpu.recommendation}
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
        </section>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="glass p-6">
          <h3 className="mb-4 text-base font-bold text-slate-900 dark:text-slate-100">
            Stream infratuzilma
          </h3>
          {streamStatus ? (
            <div className="space-y-3 text-xs text-slate-600 dark:text-slate-400">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-indigo-100 px-2.5 py-1 font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-400">
                  {streamStatus.shardingEnabled ? `${streamStatus.shardCount} shard` : '1 node'}
                </span>
                <span className="rounded-full bg-white/60 px-2.5 py-1 font-semibold dark:bg-white/10">
                  MediaMTX: {streamStatus.registeredStreams}/{streamStatus.faolCameras}
                </span>
              </div>
              <div className="space-y-1.5">
                {streamStatus.shards.map((s) => (
                  <div key={s.index} className="flex items-center justify-between rounded-lg bg-white/40 px-2.5 py-1.5 dark:bg-white/5">
                    <span>Shard {s.index}</span>
                    <span>
                      {s.reachable ? 'OK' : 'DOWN'} · {s.pathCount} path · {s.assignedCameras} kamera
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-500">
                {streamStatus.recommendation}
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
        </section>

        <section className="glass p-6">
          <h3 className="mb-4 text-base font-bold text-slate-900 dark:text-slate-100">
            Kamera tarmog'i
          </h3>
          {cameraNetwork ? (
            <div className="space-y-3 text-xs text-slate-600 dark:text-slate-400">
              <div className="flex flex-wrap gap-2">
                <span
                  className={`rounded-full px-2.5 py-1 font-semibold ${
                    cameraNetwork.reachableCameras > 0
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400'
                      : 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400'
                  }`}
                >
                  Online: {cameraNetwork.reachableCameras}/{cameraNetwork.faolCameras}
                </span>
                {cameraNetwork.linkLocalIpCount > 0 && (
                  <span className="rounded-full bg-amber-100 px-2.5 py-1 font-semibold text-amber-700 dark:bg-amber-500/15 dark:text-amber-400">
                    169.254.x: {cameraNetwork.linkLocalIpCount}
                  </span>
                )}
                {cameraNetwork.recentOfflineAlerts24h > 0 && (
                  <span className="rounded-full bg-red-100 px-2.5 py-1 font-semibold text-red-700 dark:bg-red-500/10 dark:text-red-400">
                    Ogohlantirish: {cameraNetwork.recentOfflineAlerts24h}
                  </span>
                )}
              </div>
              <p>
                Oxirgi sweep: {cameraNetwork.lastSweep.reachable}/{cameraNetwork.lastSweep.faolChecked} —{' '}
                {cameraNetwork.lastSweep.durationSeconds}s
                {cameraNetwork.lastSweep.skippedOverlap ? ' (overlap skip)' : ''}
              </p>
              {cameraNetwork.chronicOfflineCount > 0 && (
                <p className="text-red-600 dark:text-red-400">
                  {cameraNetwork.chronicOfflineCount} ta kamera uzoq vaqt offline
                </p>
              )}
              <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-500">
                {cameraNetwork.recommendation}
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-center py-6 text-slate-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
