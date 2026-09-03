import { useEffect, useRef, useState } from 'react';
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

  // Keyingi sahifaning kamera RO'YXATI (video emas) oldindan olib
  // qo'yiladi, shuning uchun "keyingi" bosilganda kutish bo'lmaydi.
  // `key` — qaysi qidiruv/filtr uchun ekanini belgilaydi: filtr
  // o'zgargach eski sahifalar avtomatik yaroqsiz bo'ladi.
  const prefetched = useRef<{ key: string; pages: Map<number, Page<CameraFeed>> }>({
    key: '',
    pages: new Map(),
  });

  // Oxirgi qidiruv/filtr — asosiy kamerani QACHON almashtirishni shu
  // hal qiladi. Sahifadan sahifaga o'tganda almashtirmaymiz (bu ataylab:
  // tanlangan kamera 8 talikda bo'lmasa ham ko'rinib turishi kerak),
  // lekin qidiruv o'zgarganda almashtiramiz — "192.168.0.36" deb qidirib,
  // ekranda butunlay boshqa kamerani ko'rib turish chalg'ituvchi.
  const lastQueryKey = useRef<string | null>(null);

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
  const queryKey = `${debouncedSearch}|${filters.building}|${statusFilter ?? ''}`;

  useEffect(() => {
    let cancelled = false;

    // Keyingi sahifa oldindan olib qo'yilgan bo'lsa — darhol ko'rsatamiz.
    // Kesh faqat AYNAN shu qidiruv/filtr uchun (queryKey) amal qiladi,
    // aks holda filtr o'zgargach eski sahifa qaytib kelib qolardi.
    const cache = prefetched.current;
    const cachedPage = cache.key === queryKey ? cache.pages.get(page) : undefined;
    if (cachedPage) {
      setCameras(cachedPage.items);
      setPageInfo({ total: cachedPage.total, totalPages: cachedPage.totalPages });
      setActiveCamera((current) => current ?? cachedPage.items[0] ?? current);
      setLoading(false);
    } else {
      setLoading(true);
    }

    function queryFor(targetPage: number) {
      return buildQuery({
        page: targetPage,
        pageSize: PAGE_SIZE,
        search: debouncedSearch || undefined,
        building: filters.building || undefined,
        status: statusFilter,
      });
    }

    // Keshdan ko'rsatilgan bo'lsa ham qayta so'raymiz: kamera holati
    // (JONLI/OFLAYN) o'zgarib turadi, kesh esa faqat "darhol ko'rinsin"
    // uchun, haqiqat manbai emas.
    api
      .get<Page<CameraFeed>>(`/api/public/cameras${queryFor(page)}`)
      .then((res) => {
        if (cancelled) return;
        setCameras(res.items);
        setPageInfo({ total: res.total, totalPages: res.totalPages });
        // Qidiruv/filtr o'zgargan bo'lsa — natijaning birinchisini
        // ko'rsatamiz. Aks holda (shunchaki sahifa almashgan bo'lsa)
        // tanlangan kameraga tegmaymiz: u joriy 8 talikda bo'lishi shart
        // emas va operator uni ataylab tanlab qo'ygan bo'lishi mumkin.
        const queryChanged = lastQueryKey.current !== queryKey;
        lastQueryKey.current = queryKey;
        if (queryChanged) {
          setActiveCamera(res.items[0] ?? null);
        } else {
          setActiveCamera((current) => current ?? res.items[0] ?? current);
        }

        // Keyingi sahifani fon rejimida oldindan olib qo'yamiz — "keyingi"
        // bosilganda so'rov-javob kutilmasin, miniatyuralar darhol
        // chizilsin va video ulanishlari o'sha zahoti boshlansin.
        //
        // Faqat MA'LUMOT oldindan olinadi, video oqimi EMAS: 8 ta
        // ko'rinmaydigan oqimni ham ochib qo'yish serverga ikki barobar
        // yuk bo'lardi — aynan biz qochayotgan narsa.
        const next = page + 1;
        if (next <= res.totalPages) {
          if (cache.key !== queryKey) {
            cache.key = queryKey;
            cache.pages.clear();
          }
          if (!cache.pages.has(next)) {
            api
              .get<Page<CameraFeed>>(`/api/public/cameras${queryFor(next)}`)
              .then((nextRes) => {
                if (cache.key === queryKey) cache.pages.set(next, nextRes);
              })
              .catch(() => {
                /* oldindan olish — ixtiyoriy optimizatsiya, xatosi jimgina o'tkaziladi */
              });
          }
        }
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
  }, [page, debouncedSearch, filters.building, statusFilter, queryKey]);

  function resetFilters(next: CameraFilters) {
    setFilters(next);
  }

  return (
    <div className="flex h-full w-full flex-col">
      <section className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Monitor — 3/4. Butun blok ekran balandligiga sig'adigan qilib
            qurilgan (scroll qilinmasin degan talab bo'yicha): sarlavha
            qatori o'z balandligini oladi (shrink-0), asosiy kamera qolgan
            bo'sh joyni egallaydi (flex-1 — endi aspect-video EMAS, shuning
            uchun tor bo'lib qolmaydi), miniatyuralar esa pastda kichik,
            belgilangan balandlikda turadi. */}
        <div className="glass flex min-h-0 flex-col gap-2.5 p-4 lg:col-span-3">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-extrabold text-slate-900 dark:text-slate-100">
                Video Monitoring Markazi
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {pageInfo.total} ta kamera · miniatyurani bosing — asosiy ko&apos;rinishga o&apos;tadi
              </p>
            </div>

            <div className="flex flex-wrap items-end gap-2">
              <span className="mb-2 flex items-center gap-1 text-[11px] font-bold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                <SlidersHorizontal size={13} className="text-indigo-500" />
                Smart Filtr
              </span>
              <CameraFilterBar filters={filters} onChange={resetFilters} buildings={stats.buildings} />
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

          <MainCameraView camera={activeCamera} className="min-h-0 flex-1" />

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

        {/* Yon panel — 1/4, mustaqil scroll qiladi (monitor balandligini
            sherigicha cho'zib, uni ham scroll qildirib qo'ymasligi uchun). */}
        <div className="min-h-0 space-y-4 overflow-y-auto lg:col-span-1">
          <ReportPanel />
          <EventsLogPanel />
          <AlarmPanel cameras={cameras} onSelectCamera={setActiveCamera} />
        </div>
      </section>
    </div>
  );
}
