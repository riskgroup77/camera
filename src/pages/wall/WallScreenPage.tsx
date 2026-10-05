import { Loader2, ShieldX } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrivalsPanel } from '../../components/wall/ArrivalsPanel';
import { CamerasPanel } from '../../components/wall/CamerasPanel';
import { RankingPanel } from '../../components/wall/RankingPanel';
import { SecurityPanel } from '../../components/wall/SecurityPanel';
import { SpotlightPanel } from '../../components/wall/SpotlightPanel';
import { TodayPanel } from '../../components/wall/TodayPanel';
import { tashkentClock, WallHeader } from '../../components/wall/WallHeader';
import { WallSettings } from '../../components/wall/WallSettings';
import { api, buildQuery, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { useLiveAttendance, useLiveEvents, type LiveAttendanceMessage } from '../../lib/realtime';
import type { LastArrival } from '../../lib/situationApi';
import {
  burnInOffset,
  buildWallQuery,
  computeWallLayout,
  getChronic,
  getSpotlightDetail,
  getWall,
  mergeArrival,
  mergeArrivalLists,
  nextRotationIndex,
  parseWallConfig,
  reconcileRotation,
  shiftIsoDate,
  spotlightKey,
  type SpotlightDetail,
  type Wall,
  type WallConfig,
  type WallHighEvent,
} from '../../lib/wallApi';
import type { AIEvent } from '../../types';

const POLL_MS = 20_000;
const CHRONIC_MS = 15 * 60_000;
const RELOAD_MS = 6 * 60 * 60_000;
const BURN_STEP_MS = 2 * 60_000;
const FRESH_MS = 8_000;
const DETAIL_TTL_MS = 60_000;
const SPOT_CACHE_MAX = 12;

const WALL_CSS = `
@keyframes wall-arrive { 0% { transform: translateY(-0.8em) scale(.97); opacity: 0 } 60% { opacity: 1 } 100% { transform: none; opacity: 1 } }
@keyframes wall-fade { from { opacity: 0 } to { opacity: 1 } }
@keyframes wall-progress { from { width: 0 } to { width: 100% } }
@keyframes wall-blink { 50% { opacity: .55 } }
@keyframes wall-alert { 0%, 100% { box-shadow: none } 50% { box-shadow: 0 0 0 .2em rgb(var(--c-danger) / .35) } }
.wall-arrive { animation: wall-arrive .7s cubic-bezier(.2,.8,.2,1) both }
.wall-fade-in { animation: wall-fade .8s ease-out both }
.wall-progress { animation-name: wall-progress; animation-timing-function: linear; animation-fill-mode: both }
.wall-blink { animation: wall-blink 2s ease-in-out infinite }
.wall-alert { animation: wall-arrive .7s both, wall-alert 1.6s ease-in-out 3 }
`;

/** Vaqtni institut (Toshkent) mintaqasida ko'rsatadi — ekran turgan
 *  kompyuterning mintaqasi noto'g'ri sozlangan bo'lsa ham to'g'ri. */
function hhmm(value: string | null | undefined): string {
  const clock = (d: Date) => `${tashkentClock(d).hh}:${tashkentClock(d).mm}`;
  if (!value) return clock(new Date());
  if (/^\d{2}:\d{2}/.test(value)) return value.slice(0, 5);
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value.slice(0, 5) : clock(d);
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function liveToArrival(m: LiveAttendanceMessage): LastArrival {
  const name = m.fullName ?? "Noma'lum";
  return {
    id: m.personId,
    fullName: name,
    photoUrl: null,
    initials: initialsOf(name),
    type: m.personType ?? 'xodim',
    unit: m.group ?? m.camera ?? '',
    faculty: null,
    time: hhmm(m.checkIn),
    status: m.status,
  } as LastArrival;
}

function useFresh() {
  const [ids, setIds] = useState<ReadonlySet<string>>(() => new Set());
  // Ekran kunlab ochiq turadi: taymerlar ro'yxati yopilganda tozalanadi.
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);
  const mark = useCallback((id: string) => {
    setIds((prev) => new Set(prev).add(id));
    // Ishlagan taymer ro'yxatdan o'zi chiqadi. Ilgari ro'yxat `slice(-50)`
    // bilan qirqilardi: bu hali ishlamagan taymerlarni ham tashlab
    // yuborardi va ular yopilganda tozalanmay qolardi.
    const timer = window.setTimeout(() => {
      timers.current = timers.current.filter((t) => t !== timer);
      setIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, FRESH_MS);
    timers.current.push(timer);
  }, []);
  const clear = useCallback(() => setIds(new Set()), []);
  return [ids, mark, clear] as const;
}

/** Kadrlar keshi faqat ekranda turgan hodisalar uchun saqlanadi: ekran
 *  kunlab ochiq turganda kesh cheksiz o'smasin. */
export function pruneSnapshots(
  map: Record<string, string | null>,
  keepIds: string,
): Record<string, string | null> {
  const keep = new Set(keepIds.split(',').filter(Boolean));
  const out: Record<string, string | null> = {};
  for (const id of Object.keys(map)) if (keep.has(id)) out[id] = map[id];
  return out;
}

function useAspect() {
  const read = () => (typeof window === 'undefined' ? 16 / 9 : window.innerWidth / Math.max(1, window.innerHeight));
  const [aspect, setAspect] = useState(read);
  useEffect(() => {
    // `resize` soniyasiga o'nlab marta keladi; har biri butun devorni
    // qayta chizardi. Kadrga bir marta yetarli.
    let raf = 0;
    const on = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        setAspect(read());
      });
    };
    window.addEventListener('resize', on);
    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', on);
    };
  }, []);
  return aspect;
}

export default function WallScreenPage() {
  const { role } = useAuth();
  const { can } = usePermissions();
  const allowed = can('viewReports', role) || can('manageAttendance', role);
  const [searchParams, setSearchParams] = useSearchParams();
  const config = useMemo(() => parseWallConfig(searchParams), [searchParams]);
  // Hodisa kadrlari /api/events dan olinadi — u reviewEvents huquqini talab qiladi.
  const canSeeEvents = can('reviewEvents', role);

  // ── Asosiy ma'lumot (bitta so'rov, 20 s)
  const [wall, setWall] = useState<Wall | null>(null);
  const [online, setOnline] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [firstError, setFirstError] = useState(false);

  useEffect(() => {
    if (!allowed) return;
    let ctrl: AbortController | null = null;
    const load = () => {
      ctrl?.abort();
      ctrl = new AbortController();
      getWall({ signal: ctrl.signal })
        .then((w) => {
          setWall(w);
          setOnline(true);
          setFirstError(false);
          setUpdatedAt(new Date());
        })
        .catch((err) => {
          if (isAbortError(err)) return;
          setOnline(false);
          setFirstError(true);
        });
    };
    load();
    const t = window.setInterval(load, POLL_MS);
    const goOffline = () => setOnline(false);
    window.addEventListener('offline', goOffline);
    window.addEventListener('online', load);
    return () => {
      window.clearInterval(t);
      ctrl?.abort();
      window.removeEventListener('offline', goOffline);
      window.removeEventListener('online', load);
    };
  }, [allowed]);

  // ── Takror kechikkanlar (14 kun, xodimlar)
  const [chronic, setChronic] = useState<number | null>(null);
  // Xato jimgina yutilib, panelda abadiy "—" turardi — sababi yoziladi.
  const [chronicError, setChronicError] = useState(false);
  const wallDate = wall?.date;
  useEffect(() => {
    if (!allowed || !wallDate || !config.panels.includes('D')) return;
    let ctrl: AbortController | null = null;
    const load = () => {
      ctrl?.abort();
      ctrl = new AbortController();
      getChronic(shiftIsoDate(wallDate, 13), wallDate, { signal: ctrl.signal })
        .then((rows) => {
          setChronic(rows.length);
          setChronicError(false);
        })
        .catch((err) => {
          if (isAbortError(err)) return;
          setChronicError(true);
        });
    };
    load();
    const t = window.setInterval(load, CHRONIC_MS);
    return () => {
      window.clearInterval(t);
      ctrl?.abort();
    };
  }, [allowed, wallDate, config.panels]);

  // ── Jonli kelishlar va hodisalar
  const [liveArrivals, setLiveArrivals] = useState<LastArrival[]>([]);
  const [liveEvents, setLiveEvents] = useState<WallHighEvent[]>([]);
  const [freshArrivals, markArrival, clearFreshArrivals] = useFresh();
  const [freshEvents, markEvent] = useFresh();

  // Yarim tundan keyin server yangi kunni beradi — kechagi jonli
  // kelishlar ekranda "bugungi" bo'lib qolmasin (ekran kunlab ochiq).
  useEffect(() => {
    if (!wallDate) return;
    setLiveArrivals([]);
    setLiveEvents([]);
    clearFreshArrivals();
  }, [wallDate, clearFreshArrivals]);

  useLiveAttendance((m) => {
    // Boshqa kunning xabari (yarim tun atrofida) ekranga tushmaydi.
    if (wallDate && m.date && m.date !== wallDate) return;
    const a = liveToArrival(m);
    setLiveArrivals((prev) => mergeArrival(prev, a, 12));
    markArrival(a.id);
  }, allowed);

  useLiveEvents((e: AIEvent & { kind?: string }) => {
    if (e.kind === 'event_updated') return;
    if (e.severity !== 'yuqori' || e.status !== 'yangi') return;
    const item: WallHighEvent = {
      id: e.id,
      moduleName: e.moduleName,
      cameraName: e.cameraName,
      building: e.building,
      time: hhmm(e.occurredAt ?? e.timestamp),
      status: e.status,
      snapshotUrl: e.snapshotUrl ?? null,
    };
    setLiveEvents((prev) => mergeArrival(prev, item, 5));
    markEvent(item.id);
  }, allowed);

  const arrivals = useMemo(
    () => mergeArrivalLists(wall?.lastArrivals ?? [], liveArrivals, 12),
    [wall?.lastArrivals, liveArrivals],
  );

  // Hodisa kadrlari: /wall ularni bermaydi — ro'yxatdan (huquq bo'lsa) olamiz.
  const [snapshots, setSnapshots] = useState<Record<string, string | null>>({});
  const highIds = (wall?.highEvents ?? []).map((e) => e.id).join(',');
  useEffect(() => {
    if (!highIds || !config.panels.includes('E') || !canSeeEvents) return;
    const missing = highIds.split(',').filter((id) => !(id in snapshots));
    if (missing.length === 0) return;
    const ctrl = new AbortController();
    api
      .get<{ items: AIEvent[] }>(
        `/api/events${buildQuery({ severity: 'yuqori', status: 'yangi,jarayonda', pageSize: 20 })}`,
        undefined,
        { signal: ctrl.signal },
      )
      .then((page) => {
        const next: Record<string, string | null> = {};
        for (const id of missing) next[id] = null;
        for (const ev of page.items) next[ev.id] = ev.snapshotUrl ?? null;
        setSnapshots((prev) => pruneSnapshots({ ...prev, ...next }, highIds));
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setSnapshots((prev) =>
          pruneSnapshots({ ...prev, ...Object.fromEntries(missing.map((id) => [id, null])) }, highIds),
        );
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- snapshots faqat keshni tekshirish uchun
  }, [highIds, config.panels, canSeeEvents]);

  const highEvents = useMemo(() => {
    const server = wall?.highEvents ?? [];
    const ids = new Set(server.map((e) => e.id));
    const extra = liveEvents.filter((e) => !ids.has(e.id));
    return [...extra, ...server]
      .slice(0, 5)
      .map((e) => ({ ...e, snapshotUrl: e.snapshotUrl ?? snapshots[e.id] ?? null }));
  }, [wall?.highEvents, liveEvents, snapshots]);

  // ── Spotlight aylanishi
  const spotlight = useMemo(() => wall?.spotlight ?? [], [wall?.spotlight]);
  const [spotIndex, setSpotIndex] = useState(0);
  const [cycleKey, setCycleKey] = useState(0);
  const currentKeyRef = useRef<string | null>(null);
  const cacheRef = useRef(new Map<string, { detail: SpotlightDetail; at: number }>());
  const [detail, setDetail] = useState<SpotlightDetail | null>(null);
  const spotOn = config.panels.includes('C');

  useEffect(() => {
    setSpotIndex((i) => reconcileRotation(currentKeyRef.current, i, spotlight));
  }, [spotlight]);

  useEffect(() => {
    if (!spotOn || spotlight.length < 2) return;
    const t = window.setInterval(() => {
      setSpotIndex((i) => nextRotationIndex(i, spotlight.length));
      setCycleKey((k) => k + 1);
    }, config.rotate * 1000);
    return () => window.clearInterval(t);
  }, [spotOn, spotlight.length, config.rotate]);

  const current = spotlight[spotIndex] ?? null;
  const currentKey = current ? spotlightKey(current) : null;
  currentKeyRef.current = currentKey;

  useEffect(() => {
    if (!spotOn || !current) return;
    const ctrl = new AbortController();
    const fetchOne = (item: typeof current, show: boolean) => {
      const key = spotlightKey(item);
      const hit = cacheRef.current.get(key);
      if (hit && Date.now() - hit.at < DETAIL_TTL_MS) {
        if (show) setDetail(hit.detail);
        return;
      }
      getSpotlightDetail(item, { signal: ctrl.signal })
        .then((d) => {
          const cache = cacheRef.current;
          cache.set(key, { detail: d, at: Date.now() });
          // Ekran kunlab ochiq: eskirganlari va ortiqchasi tashlanadi
          // (yuzlar ro'yxati — xotirada eng og'ir qism).
          const now = Date.now();
          for (const [k, v] of cache) if (now - v.at > DETAIL_TTL_MS) cache.delete(k);
          while (cache.size > SPOT_CACHE_MAX) cache.delete(cache.keys().next().value as string);
          if (show) setDetail(d);
        })
        .catch(() => {
          /* keyingisiga o'tamiz; eskisi ekranda qoladi */
        });
    };
    fetchOne(current, true);
    const next = spotlight[nextRotationIndex(spotIndex, spotlight.length)];
    if (next && spotlightKey(next) !== currentKey) {
      const t = window.setTimeout(() => fetchOne(next, false), 2000);
      return () => {
        window.clearTimeout(t);
        ctrl.abort();
      };
    }
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- kalit o'zgarganda yoki poll kelganda
  }, [spotOn, currentKey, wall?.generatedAt]);

  // ── Kamera paneli mavjudligi
  const [camsAvailable, setCamsAvailable] = useState(true);
  const onCams = useCallback((has: boolean) => setCamsAvailable(has), []);
  // Sozlamalarda o'chirilgan kamera ekran sozlamasida (`?cameras=`)
  // qolib ketmasin. Tozalash faqat ishonchli ro'yxat bilan bo'ladi —
  // CamerasPanel xato yoki bo'sh javobda buni umuman chaqirmaydi.
  const onPruneCams = useCallback(
    (ids: string[]) => {
      setSearchParams(new URLSearchParams(buildWallQuery({ ...config, cameras: ids })), { replace: true });
    },
    [config, setSearchParams],
  );
  const effectivePanels = config.panels.filter((p) => p !== 'F' || camsAvailable);

  // ── Joylashuv
  const aspect = useAspect();
  const layout = computeWallLayout(effectivePanels, aspect);

  // ── Kuyishdan himoya, 6 soatda qayta yuklash
  const [burnStep, setBurnStep] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setBurnStep((s) => s + 1), BURN_STEP_MS);
    const r = window.setTimeout(() => window.location.reload(), RELOAD_MS);
    return () => {
      window.clearInterval(t);
      window.clearTimeout(r);
    };
  }, []);
  const [dx, dy] = burnInOffset(burnStep);

  // ── Klaviatura: S — sozlamalar, F — to'liq ekran
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = Boolean(t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'));
      // Escape maydon ichida turganda ham oynani yopadi — aks holda
      // sozlamadan chiqishning yagona yo'li sichqoncha bo'lib qolardi.
      if (e.key === 'Escape') {
        setSettingsOpen(false);
        return;
      }
      if (typing) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 's' || e.key === 'S') setSettingsOpen((o) => !o);
      if (e.key === 'f' || e.key === 'F') {
        if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
        else void document.documentElement.requestFullscreen?.().catch(() => undefined);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const applyConfig = (cfg: WallConfig) => {
    setSearchParams(new URLSearchParams(buildWallQuery(cfg)), { replace: true });
    setSettingsOpen(false);
  };

  useEffect(() => {
    const prev = document.title;
    document.title = 'Situatsion markaz — ekran';
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div
      className="fixed inset-0 overflow-hidden bg-bg text-fg"
      // Zaldan o'qiladigan ekran: asos o'lcham KATTALASHTIRILDI — barcha
      // ichki o'lchamlar `em` da, shuning uchun butun devor bir xil o'sadi.
      style={{ fontSize: 'clamp(12px, min(1.75vh, 1.08vw), 48px)' }}
    >
      <style>{WALL_CSS}</style>
      <div
        className="flex h-full w-full flex-col gap-[0.9em] p-[1em] transition-transform duration-[3000ms]"
        style={{ transform: `translate(${dx}px, ${dy}px)` }}
      >
        <WallHeader online={online} updatedAt={updatedAt} />
        {!allowed ? (
          <Centered icon={<ShieldX className="h-[3em] w-[3em] text-danger" />} title="Ruxsat yo'q" />
        ) : !wall ? (
          <Centered
            icon={<Loader2 className="h-[3em] w-[3em] animate-spin text-muted" />}
            title={firstError ? 'Aloqa yo\'q' : 'Yuklanmoqda…'}
          />
        ) : (
          <main
            className="grid min-h-0 flex-1 gap-[0.9em]"
            style={{ gridTemplateColumns: layout.columns, gridTemplateRows: layout.rows, gridTemplateAreas: layout.areas }}
          >
            {effectivePanels.includes('A') && (
              <TodayPanel
                students={wall.students}
                staff={wall.staff}
                studentsDataAvailable={wall.studentsDataAvailable}
                studentsEnroll={wall.enrollment.students}
                facultyEnroll={wall.enrollment.byFaculty}
              />
            )}
            {effectivePanels.includes('B') && <ArrivalsPanel arrivals={arrivals} freshIds={freshArrivals} live={online} />}
            {effectivePanels.includes('C') && (
              <SpotlightPanel
                detail={detail}
                index={spotIndex}
                total={spotlight.length}
                rotateS={config.rotate}
                cycleKey={cycleKey}
              />
            )}
            {effectivePanels.includes('D') && <RankingPanel top={wall.topUnits} bottom={wall.bottomUnits} chronic={chronic} chronicError={chronicError} />}
            {effectivePanels.includes('E') && (
              <SecurityPanel
                events={highEvents}
                camerasOnline={wall.camerasOnline}
                camerasTotal={wall.camerasTotal}
                highOpen={wall.highOpen}
                freshIds={freshEvents}
              />
            )}
            {config.panels.includes('F') && (
              <CamerasPanel ids={config.cameras} onAvailability={onCams} onPrune={onPruneCams} />
            )}
          </main>
        )}
      </div>
      {settingsOpen && <WallSettings config={config} onApply={applyConfig} onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

function Centered({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-[0.6em] text-center">
      {icon}
      <div className="text-[1.9em] font-semibold tracking-tight text-fg">{title}</div>
    </div>
  );
}
