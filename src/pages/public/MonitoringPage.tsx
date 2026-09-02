import { useEffect, useMemo, useState } from 'react';
import { Search, SlidersHorizontal } from 'lucide-react';
import CameraFilterBar, { EMPTY_FILTERS, type CameraFilters } from '../../components/CameraFilterBar';
import MainCameraView from '../../components/monitor/MainCameraView';
import CameraThumbnailStrip, { THUMBS_PER_PAGE } from '../../components/monitor/CameraThumbnailStrip';
import ReportPanel from '../../components/monitor/ReportPanel';
import EventsLogPanel from '../../components/monitor/EventsLogPanel';
import AlarmPanel from '../../components/monitor/AlarmPanel';
import { api, buildQuery, type Page } from '../../lib/apiClient';
import type { AttendanceStats, CameraFeed } from '../../types';

const PAGE_SIZE = THUMBS_PER_PAGE;
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
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filters, setFilters] = useState<CameraFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [activeCamera, setActiveCamera] = useState<CameraFeed | null>(null);

  const [cameras, setCameras] = useState<CameraFeed[]>([]);
  const [pageInfo, setPageInfo] = useState({ total: 0, totalPages: 1 });
  const [stats, setStats] = useState<AttendanceStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);

  // Qidiruv har bosilgan tugmada emas, foydalanuvchi to'xtaganda so'rov
  // yuboradi — endi qidiruv serverda bajariladi (kameralar soni ko'payganda
  // ularning hammasini oldindan yuklab olish shart emas).
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const statusFilter = filters.status === 'JONLI' ? 'live' : filters.status === 'OFLAYN' ? 'offline' : undefined;

  // Statistikalar (jami/jonli/oflayn kameralar, binolar ro'yxati) — Smart
  // Filtr'ning tezkor ko'rsatkichlari va bino ro'yxati shundan olinadi.
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

  // Joriy 8 talik sahifani serverdan yuklaydi — javob chegaralangan
  // Page<T> (app/pagination.py), shuning uchun kameralar soni ortsa ham
  // bitta so'rov hajmi cheklangan bo'lib qoladi. Eskisidek to'plab
  // borish ("load more") o'rniga endi har sahifa avvalgisini almashtiradi
  // — kichik miniatyuralar panelida haqiqiy oldingi/keyingi navigatsiya
  // kutiladi.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

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
        setCameras(res.items);
        setPageInfo({ total: res.total, totalPages: res.totalPages });
        // Faqat birinchi marta (hali hech narsa tanlanmaganda) asosiy
        // ko'rinish uchun birinchi kamerani avtomatik tanlaydi — asosiy
        // kamera tanlangandan keyin miniatyuralar sahifasini almashtirish
        // uni o'zgartirmasligi kerak (asosiy kamera joriy 8 talikda
        // bo'lishi shart emas).
        setActiveCamera((current) => current ?? res.items[0] ?? current);
      })
      .catch(() => {
        /* kameralarni yuklab bo'lmadi — bo'sh ro'yxat/oldingi holat bilan davom etamiz, texnik xatoni ko'rsatmaymiz */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, debouncedSearch, filters.building, statusFilter]);

  const quickStats = useMemo(
    () => ({
      live: stats.liveCameras,
      risk: stats.violations,
      offline: stats.offlineCameras,
      late: stats.late,
    }),
    [stats],
  );

  function resetFilters(next: CameraFilters) {
    setFilters(next);
  }

  return (
    <div className="w-full">
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Monitor — 3/4 */}
        <div className="glass space-y-4 p-6 lg:col-span-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-extrabold text-slate-900 dark:text-slate-100">
                Video Monitoring Markazi
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {pageInfo.total} ta kamera · miniatyurani bosing — asosiy ko&apos;rinishga o&apos;tadi
              </p>
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

          <div className="glass-deep p-3">
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <SlidersHorizontal size={13} className="text-indigo-500" />
              Smart Filtr
            </h3>
            <CameraFilterBar filters={filters} onChange={resetFilters} stats={quickStats} buildings={stats.buildings} />
          </div>

          <MainCameraView camera={activeCamera} />

          <CameraThumbnailStrip
            cameras={cameras}
            activeId={activeCamera?.id ?? null}
            onSelect={setActiveCamera}
            page={page}
            totalPages={pageInfo.totalPages}
            total={pageInfo.total}
            onPageChange={setPage}
            loading={loading}
          />
        </div>

        {/* Yon panel — 1/4 */}
        <div className="space-y-4 lg:col-span-1">
          <ReportPanel />
          <EventsLogPanel />
          <AlarmPanel cameras={cameras} onSelectCamera={setActiveCamera} />
        </div>
      </section>
    </div>
  );
}
