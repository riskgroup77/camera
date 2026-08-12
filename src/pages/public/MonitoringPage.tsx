import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Clock3, LogOut, Loader2, Moon, Search, Trophy, UserCheck, Users, UserX } from 'lucide-react';
import StatCard from '../../components/StatCard';
import CameraCard from '../../components/CameraCard';
import CameraFilterBar, { EMPTY_FILTERS, type CameraFilters } from '../../components/CameraFilterBar';
import CameraDetailModal from '../../components/CameraDetailModal';
import TopStudentsModal from '../../components/TopStudentsModal';
import QuickAccessBar from '../../components/QuickAccessBar';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AttendanceStats, CameraFeed } from '../../types';

const PAGE_SIZE = 30;

const EMPTY_STATS: AttendanceStats = {
  totalStudents: 0,
  present: 0,
  absent: 0,
  late: 0,
  sleepIncidents: 0,
  violations: 0,
};

export default function MonitoringPage() {
  const navigate = useNavigate();
  const { role, logout } = useAuth();
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<CameraFilters>(EMPTY_FILTERS);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [selectedCamera, setSelectedCamera] = useState<CameraFeed | null>(null);
  const [leaderboardOpen, setLeaderboardOpen] = useState(false);

  const [cameras, setCameras] = useState<CameraFeed[]>([]);
  const [stats, setStats] = useState<AttendanceStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.get<CameraFeed[]>('/api/public/cameras'), api.get<AttendanceStats>('/api/public/stats')])
      .then(([camerasRes, statsRes]) => {
        if (cancelled) return;
        setCameras(camerasRes);
        setStats(statsRes);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const attendanceRate = stats.totalStudents > 0 ? Math.round((stats.present / stats.totalStudents) * 100) : 0;

  const buildings = useMemo(() => Array.from(new Set(cameras.map((c) => c.building))).sort(), [cameras]);

  const quickStats = useMemo(
    () => ({
      live: cameras.filter((c) => c.status === 'live').length,
      risk: stats.violations,
      offline: cameras.filter((c) => c.status === 'offline').length,
      late: stats.late,
    }),
    [cameras, stats],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cameras.filter((c) => {
      if (q && !c.name.toLowerCase().includes(q) && !c.zone.toLowerCase().includes(q)) return false;
      if (filters.building && c.building !== filters.building) return false;
      if (filters.status) {
        const wantLive = filters.status === 'JONLI';
        if ((c.status === 'live') !== wantLive) return false;
      }
      return true;
    });
  }, [cameras, search, filters]);

  const visible = filtered.slice(0, visibleCount);
  const remaining = filtered.length - visible.length;

  function resetFilters(next: CameraFilters) {
    setFilters(next);
    setVisibleCount(PAGE_SIZE);
  }

  return (
    <div className="mx-auto max-w-[1600px] space-y-4">
      <section className="glass p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-extrabold text-slate-900 dark:text-slate-100">
            Bugungi Davomat Statistikasi
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setLeaderboardOpen(true)}
              className="btn-glass flex items-center gap-1.5"
            >
              <Trophy size={14} />
              Namunali talabalar
            </button>
            <button
              onClick={() => {
                if (role) logout();
                navigate('/admin/login');
              }}
              className="glass-btn-danger flex items-center gap-1.5 !py-2"
            >
              <LogOut size={14} />
              Chiqish
            </button>
          </div>
        </div>

        <div className="mb-4">
          <QuickAccessBar />
        </div>

        {error && (
          <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="mb-4 rounded-xl bg-indigo-50/70 dark:bg-indigo-500/10 p-3 text-sm">
          <span className="font-semibold text-indigo-700 dark:text-indigo-400">Umumiy davomat: </span>
          <span className="text-indigo-900 dark:text-indigo-300">
            {attendanceRate}% ({stats.present}/{stats.totalStudents})
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard
            icon={<Users size={20} />}
            value={stats.totalStudents.toLocaleString('ru-RU')}
            label="Jami talabalar"
            sublabel="Barcha kurslar"
            tone="indigo"
          />
          <StatCard
            icon={<UserCheck size={20} />}
            value={stats.present}
            label="Qatnashganlar"
            sublabel={`${attendanceRate}% davomat`}
            tone="green"
          />
          <StatCard
            icon={<UserX size={20} />}
            value={stats.absent}
            label="Kelmaydiganlar"
            sublabel="Sababsiz"
            tone="red"
          />
          <StatCard icon={<Moon size={20} />} value={stats.sleepIncidents} label="Uyquda" sublabel="Darsda uyquda" tone="amber" />
          <StatCard
            icon={<AlertTriangle size={20} />}
            value={stats.violations}
            label="Qoidabuzarlik"
            sublabel="Xavf aniqlandi"
            tone="red"
          />
          <StatCard
            icon={<Clock3 size={20} />}
            value={stats.late}
            label="Kechikish"
            sublabel="Kech kelganlar"
            tone="amber"
          />
        </div>
      </section>

      <section className="glass p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900 dark:text-slate-100">
              Video Monitoring Markazi
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {filtered.length} ta kamera topildi · {visible.length} ta ko'rsatilmoqda
              (kamerani bosing — batafsil ma'lumot)
            </p>
          </div>

          <div className="relative w-full max-w-xs">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
            />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setVisibleCount(PAGE_SIZE);
              }}
              placeholder="Kamera nomi yoki zona bo'yicha qidiruv..."
              aria-label="Kameralarni qidirish"
              className="w-full rounded-xl border border-white/80 dark:border-white/10 bg-white/60 dark:bg-white/5 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 dark:text-slate-500 focus:border-indigo-300"
            />
          </div>
        </div>

        <CameraFilterBar filters={filters} onChange={resetFilters} stats={quickStats} buildings={buildings} />

        {loading && cameras.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-slate-400">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : visible.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
            Filtrlarga mos kamera topilmadi
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {visible.map((camera) => (
              <CameraCard
                key={camera.id}
                camera={camera}
                onClick={() => setSelectedCamera(camera)}
              />
            ))}
          </div>
        )}

        {remaining > 0 && (
          <div className="mt-6 flex justify-center">
            <button
              onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
              className="btn-glass"
            >
              Ko'proq ko'rsatish (+{Math.min(PAGE_SIZE, remaining)} kamera)
            </button>
          </div>
        )}
      </section>

      <CameraDetailModal camera={selectedCamera} onClose={() => setSelectedCamera(null)} />
      <TopStudentsModal open={leaderboardOpen} onClose={() => setLeaderboardOpen(false)} />
    </div>
  );
}
