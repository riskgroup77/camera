import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Clock3, LogOut, Loader2, Moon, Search, Trophy, UserCheck, Users, UserX } from 'lucide-react';
import StatCard from '../../components/StatCard';
import CameraFilterBar, { EMPTY_FILTERS, type CameraFilters } from '../../components/CameraFilterBar';
import CameraDetailModal from '../../components/CameraDetailModal';
import VirtualCameraGrid from '../../components/VirtualCameraGrid';
import type { GridLayoutMode } from '../../lib/virtualCameraGrid';
import TopStudentsModal from '../../components/TopStudentsModal';
import QuickAccessBar from '../../components/QuickAccessBar';
import { api, buildQuery, type Page } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { AttendanceStats, CameraFeed } from '../../types';

const PAGE_SIZE = 30;
const SEARCH_DEBOUNCE_MS = 300;

const EMPTY_STATS: AttendanceStats = {
  totalStudents: 0,
  present: 0,
  absent: 0,
  late: 0,
  sleepIncidents: 0,
  violations: 0,
  liveCameras: 0,
  offlineCameras: 0,
  buildings: [],
};

export default function MonitoringPage() {
  const navigate = useNavigate();
  const { role, logout } = useAuth();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filters, setFilters] = useState<CameraFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [selectedCamera, setSelectedCamera] = useState<CameraFeed | null>(null);
  const [leaderboardOpen, setLeaderboardOpen] = useState(false);
  const [layoutMode, setLayoutMode] = useState<GridLayoutMode>('scroll');

  const [cameras, setCameras] = useState<CameraFeed[]>([]);
  const [pageInfo, setPageInfo] = useState({ total: 0, totalPages: 1 });
  const [stats, setStats] = useState<AttendanceStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Qidiruv har bosilgan tugmada emas, foydalanuvchi to'xtaganda so'rov
  // yuboradi — endi qidiruv serverda bajariladi (kameralar soni ko'payganda
  // ularning hammasini oldindan yuklab olish shart emas).
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const statusFilter = filters.status === 'JONLI' ? 'live' : filters.status === 'OFLAYN' ? 'offline' : undefined;

  // Statistikalar (jami/jonli/oflayn kameralar, binolar ro'yxati) —
  // sahifalash va filtrlardan mustaqil, alohida so'raladi.
  useEffect(() => {
    let cancelled = false;
    api
      .get<AttendanceStats>('/api/public/stats')
      .then((res) => {
        if (!cancelled) setStats(res);
      })
      .catch(() => {
        /* statistikani yuklab bo'lmadi — standart (bo'sh) qiymatlar bilan davom etamiz */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Qidiruv yoki filtr o'zgarsa — birinchi sahifadan qayta boshlaymiz.
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters.building, statusFilter]);

  // Joriy sahifani (yoki "Ko'proq ko'rsatish" bosilganda keyingi sahifani)
  // serverdan yuklaydi — javob endi bitta katta massiv emas, chegaralangan
  // Page<T> (app/pagination.py), shuning uchun kameralar soni ortsa ham
  // bitta so'rov hajmi cheklangan bo'lib qoladi.
  useEffect(() => {
    let cancelled = false;
    if (page === 1) setLoading(true);
    else setLoadingMore(true);

    const qs = buildQuery({
      page,
      pageSize: PAGE_SIZE,
      search: debouncedSearch || undefined,
      building: filters.building || undefined,
      status: statusFilter,
    });

    api
      .get<Page<CameraFeed>>(`/api/public/cameras${qs}`)
      .then((res) => {
        if (cancelled) return;
        setCameras((prev) => (page === 1 ? res.items : [...prev, ...res.items]));
        setPageInfo({ total: res.total, totalPages: res.totalPages });
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setLoadingMore(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [page, debouncedSearch, filters.building, statusFilter]);

  const attendanceRate = stats.totalStudents > 0 ? Math.round((stats.present / stats.totalStudents) * 100) : 0;

  const quickStats = useMemo(
    () => ({
      live: stats.liveCameras,
      risk: stats.violations,
      offline: stats.offlineCameras,
      late: stats.late,
    }),
    [stats],
  );

  const visible = cameras;
  const remaining = pageInfo.total - cameras.length;

  function resetFilters(next: CameraFilters) {
    setFilters(next);
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
              {pageInfo.total} ta kamera topildi · {visible.length} ta ko'rsatilmoqda
              (kamerani bosing — batafsil ma'lumot · bir vaqtda max 8 ta jonli oqim)
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ['scroll', 'Ro\'yxat'],
                ['wall-4', '4 ta devor'],
                ['wall-9', '9 ta devor'],
                ['wall-16', '16 ta devor'],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setLayoutMode(mode)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors ${
                  layoutMode === mode
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="relative w-full max-w-xs">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Kamera nomi yoki zona bo'yicha qidiruv..."
              aria-label="Kameralarni qidirish"
              className="w-full rounded-xl border border-white/80 dark:border-white/10 bg-white/60 dark:bg-white/5 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 dark:text-slate-500 focus:border-indigo-300"
            />
          </div>
        </div>

        <CameraFilterBar filters={filters} onChange={resetFilters} stats={quickStats} buildings={stats.buildings} />

        {loading && cameras.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-slate-400">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : visible.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
            Filtrlarga mos kamera topilmadi
          </p>
        ) : (
          <VirtualCameraGrid
            cameras={visible}
            layoutMode={layoutMode}
            onSelect={setSelectedCamera}
          />
        )}

        {layoutMode === 'scroll' && remaining > 0 && (
          <div className="mt-6 flex justify-center">
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={loadingMore}
              className="btn-glass disabled:opacity-60"
            >
              {loadingMore ? "Yuklanmoqda..." : `Ko'proq ko'rsatish (+${Math.min(PAGE_SIZE, remaining)} kamera)`}
            </button>
          </div>
        )}
      </section>

      <CameraDetailModal camera={selectedCamera} onClose={() => setSelectedCamera(null)} />
      <TopStudentsModal open={leaderboardOpen} onClose={() => setLeaderboardOpen(false)} />
    </div>
  );
}
