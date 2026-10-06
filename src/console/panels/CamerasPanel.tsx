import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowLeft, Building2, ChevronRight, Search, Video, X } from 'lucide-react';
import { cn } from '../../ui';
import { CodeText, MicroLabel } from '../../ui/intel';
import LiveVideoPlayer from '../../components/LiveVideoPlayer';
import type { LiveDetectionResult } from '../../types';
import CameraThumbnail from '../../components/videowall/CameraThumbnail';
import PtzControls from '../../components/ptz/PtzControls';
import { usePtzAvailability } from '../../components/ptz/usePtzAvailability';
import { useWallCameras } from '../../components/videowall/useWallCameras';
import { usePageVisible } from '../../components/videowall/usePageVisible';
import { buildCameraCodes, cameraCode, cameraPlaceCode } from '../../components/videowall/cameraCode';
import type { CameraFeed } from '../../types';
import Panel from '../Panel';
import { prewarmWebrtc } from '../../lib/webrtcStream';
import { EASE, panelIn, stagger } from '../motion';
import { useVideoFlow } from '../useVideoFlow';
import { mergeSeenPeople, type SeenPerson } from '../recognizedPeople';
import { PersonQuickView, RecognizedRail } from './RecognizedRail';
import {
  EMPTY_FILTER,
  WALL_LAYOUTS,
  buildingCards,
  buildingOptions,
  roomCards,
  cameraStats,
  filterCameras,
  floorLabel,
  floorOptions,
  isStreaming,
  layoutColumns,
  rankCameras,
  type CameraFilter,
  type WallLayout,
} from '../cameraPick';

/**
 * KAMERALAR paneli.
 *
 * Yig'ilgan holat — 4 ta katak va bitta son: nechta kamera tasvir
 * uzatmoqda. Ko'proq katak ochilmaydi, chunki har katak = bitta HLS
 * oqimi = MediaMTX'da bitta o'quvchi; konsol soatlab ochiq turadi.
 *
 * Yoyilgan holat — butun devor: filtr, 4/9/16 setkasi va bitta kamerani
 * kattalashtirish (PTZ bilan, agar kamera qo'llab-quvvatlasa). Bu yerda
 * ichki siljish (scroll) ruxsat etilgan.
 *
 * Oqim hisobi (ataylab qattiq chegaralangan):
 *   yig'ilgan  — 4 tagacha;
 *   yoyilgan   — setka tanlovicha 4/9/16 tagacha;
 *   kattalashtirilgan — ATIGI 1 (devor kataklari kadrga o'tadi);
 *   varaq fonda — 0.
 */

/** Xona tanlangach video shuncha vaqt "yuklanmoqda" pardasi ostida ochiladi
 *  (oqim shu paytda isinadi — parda ketganda tasvir tayyor). */
export const CAMERA_LOAD_MS = 5_000;
/** Parda kamida shuncha turadi — tayyor oqimda ham bir zumda "miltillab"
 *  yo'qolmasin. Birinchi kadr kelishi bilan (lekin shundan oldin emas)
 *  ochiladi; kadr kelmasa — CAMERA_LOAD_MS da baribir ochiladi. */
export const CAMERA_LOAD_MIN_MS = 600;

/** Parda qachon ochiladi: birinchi kadr + kamida MIN, yoki MAX tugadi. */
export function coverDone(elapsedMs: number, firstFrame: boolean): boolean {
  return elapsedMs >= CAMERA_LOAD_MS || (firstFrame && elapsedMs >= CAMERA_LOAD_MIN_MS);
}

/** Kadr balandligi bo'yicha qisqa nom: 2160 -> 4K, 1440 -> 2K, 1080 -> FHD, 720 -> 720p. */
export function resolutionLabel(height: number | null | undefined): string | null {
  if (!height || height <= 0) return null;
  if (height >= 2000) return '4K';
  if (height >= 1400) return '2K';
  if (height >= 1000) return 'FHD';
  return `${height}p`;
}

/** Tashqaridan (Ctrl+K) "shu kamerani kattalashtir" so'rovi. */
export interface FocusRequest {
  id: string;
  nonce: number;
}

export default function CamerasPanel({
  expanded,
  onExpand,
  area,
  focusRequest = null,
}: {
  focusRequest?: FocusRequest | null;
  expanded: boolean;
  onExpand: (id: string | null) => void;
  area?: string;
}) {
  const { cameras, loading, error, refreshStreams } = useWallCameras();
  const pageVisible = usePageVisible(3_000);

  const stats = useMemo(() => cameraStats(cameras), [cameras]);
  const codes = useMemo(() => buildCameraCodes(cameras), [cameras]);
  // Kirishda hech bir kamera ochilmaydi: avval bino, keyin xona tanlanadi.
  const [building, setBuilding] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [stageId, setStageId] = useState<string | null>(null);
  const [pickedAt, setPickedAt] = useState(0);
  const buildings = useMemo(() => buildingCards(cameras), [cameras]);
  const rooms = useMemo(() => {
    if (query.trim()) return rankCameras(filterCameras(cameras, { ...EMPTY_FILTER, q: query }));
    return building ? roomCards(cameras, building) : [];
  }, [cameras, building, query]);
  const stage = stageId ? cameras.find((c) => c.id === stageId) ?? null : null;
  const pick = (id: string) => {
    setStageId(id);
    setPickedAt(Date.now());
  };

  return (
    <Panel
      id="cameras"
      title="Kameralar"
      live={stats.flowing > 0}
      expanded={expanded}
      onExpand={onExpand}
      area={area}
      clickToExpand={false}
      badge={
        <CodeText className="text-[11px] text-muted">
          {stats.total === 0 ? '—' : `${stats.flowing}/${stats.live}`}
        </CodeText>
      }
      full={
        <CameraWall
          cameras={cameras}
          codes={codes}
          stats={stats}
          loading={loading}
          error={error}
          pageVisible={pageVisible}
          onStreamUnavailable={refreshStreams}
          focusRequest={focusRequest}
        />
      }
    >
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-baseline gap-2 px-3 pb-1 pt-2">
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: EASE }}
            className="intel-code text-[clamp(20px,3vh,34px)] font-semibold leading-none"
          >
            {stats.total === 0 ? '—' : stats.flowing}
            {stats.total > 0 && <span className="text-[0.5em] font-medium text-muted">/{stats.live}</span>}
          </motion.span>
          <span className="truncate text-[11px] text-muted">
            {stats.total === 0 ? (loading ? 'yuklanmoqda…' : "ma'lumot yo'q") : 'tasvir uzatmoqda'}
          </span>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-1 p-1">
          {stage ? (
            <StageCamera
              key={`${stage.id}-${pickedAt}`}
              camera={stage}
              code={cameraCode(codes, stage.id)}
              playing={pageVisible && !expanded}
              onStreamUnavailable={refreshStreams}
              onClose={() => setStageId(null)}
            />
          ) : (
            <PickPlaceholder
              message={error ? 'Aloqa yo‘q' : loading && cameras.length === 0 ? 'Yuklanmoqda' : null}
              building={building}
            />
          )}
          <div className="flex shrink-0 items-center gap-1.5 px-0.5 pt-0.5">
            <label className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-control border border-border bg-surface px-2.5">
              <Search size={14} aria-hidden="true" className="shrink-0 text-subtle" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Kamera: nomi, xona yoki zona"
                aria-label="Kamerani qidirish"
                className="h-full min-w-0 flex-1 bg-transparent text-[12px] outline-none"
              />
              {query && (
                <button type="button" onClick={() => setQuery('')} aria-label="Tozalash" className="text-subtle hover:text-fg">
                  <X size={13} />
                </button>
              )}
            </label>
          </div>
          {query.trim() || building ? (
            <RoomStrip
              title={query.trim() ? `Qidiruv: ${rooms.length} ta kamera` : building ?? ''}
              rooms={rooms}
              codes={codes}
              activeId={stage?.id ?? null}
              onPick={pick}
              onBack={
                query.trim()
                  ? () => setQuery('')
                  : () => {
                      setBuilding(null);
                    }
              }
            />
          ) : (
            <BuildingStrip buildings={buildings} onPick={setBuilding} loading={loading && cameras.length === 0} />
          )}
        </div>
      </div>
    </Panel>
  );
}

/** Yoyilgan panel — to'liq kamera devori. */
function CameraWall({
  cameras,
  codes,
  stats,
  loading,
  error,
  pageVisible,
  onStreamUnavailable,
  focusRequest,
}: {
  focusRequest: FocusRequest | null;
  cameras: CameraFeed[];
  codes: ReadonlyMap<string, string>;
  stats: { flowing: number; live: number; total: number };
  loading: boolean;
  error: string | null;
  pageVisible: boolean;
  onStreamUnavailable: () => void;
}) {
  const [filter, setFilter] = useState<CameraFilter>(EMPTY_FILTER);
  const [layout, setLayout] = useState<WallLayout>(9);
  const [focusId, setFocusId] = useState<string | null>(null);

  const buildings = useMemo(() => buildingOptions(cameras), [cameras]);
  const floors = useMemo(() => floorOptions(cameras), [cameras]);
  const shown = useMemo(
    () => rankCameras(filterCameras(cameras, filter)),
    [cameras, filter],
  );
  const focus = useMemo(() => shown.find((camera) => camera.id === focusId) ?? null, [shown, focusId]);

  // Palitradan tanlangan kamera: filtr tozalanadi (u yashirib qo'ymasin) va kamera kattalashadi.
  useEffect(() => {
    if (!focusRequest) return;
    setFilter(EMPTY_FILTER);
    setFocusId(focusRequest.id);
  }, [focusRequest]);

  // Filtr o'zgarib, tanlangan kamera ro'yxatdan chiqib ketsa — yopamiz.
  useEffect(() => {
    if (focusId && !focus) setFocusId(null);
  }, [focusId, focus]);

  // Esc: avval kattalashtirilgan kamera yopiladi, panel esa ochiq qoladi.
  // Tutqich `capture` bosqichida — ConsoleShell'ning oyna tinglovchisi
  // shu bosqichdan keyin ishlaydi, shuning uchun to'xtatib turamiz.
  useEffect(() => {
    if (!focusId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      setFocusId(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [focusId]);

  const columns = layoutColumns(layout);
  const ptzAvailable = usePtzAvailability(focus?.id ?? null, focus?.ptzEnabled);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/70 px-3 py-2">
        <label className="glass flex h-8 min-w-0 flex-1 items-center gap-2 rounded-[5px] px-2.5 sm:max-w-xs">
          <Search size={14} aria-hidden="true" className="shrink-0 text-subtle" />
          <input
            value={filter.q}
            onChange={(event) => setFilter((prev) => ({ ...prev, q: event.target.value }))}
            placeholder="Kamera nomi"
            aria-label="Kamera qidirish"
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-subtle"
          />
        </label>

        <select
          value={filter.building}
          onChange={(event) => setFilter((prev) => ({ ...prev, building: event.target.value }))}
          aria-label="Bino"
          className="glass h-8 rounded-[5px] px-2 text-[12.5px] outline-none"
        >
          <option value="">Barcha binolar</option>
          {buildings.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>

        <select
          value={filter.floor}
          onChange={(event) => setFilter((prev) => ({ ...prev, floor: event.target.value }))}
          aria-label="Qavat"
          className="glass h-8 rounded-[5px] px-2 text-[12.5px] outline-none"
        >
          <option value="">Barcha qavatlar</option>
          {floors.map((value) => (
            <option key={value} value={value}>
              {floorLabel(value)}
            </option>
          ))}
        </select>

        <div className="glass flex h-8 items-center rounded-[5px] p-0.5" role="group" aria-label="Setka">
          {WALL_LAYOUTS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setLayout(value)}
              aria-pressed={layout === value}
              className={cn(
                'intel-code h-7 rounded-[4px] px-2 text-[12px] transition-colors',
                layout === value ? 'bg-primary text-primary-fg' : 'text-muted hover:bg-white/70',
              )}
            >
              {value}
            </button>
          ))}
        </div>

        <span className="ms-auto flex items-center gap-2">
          <CodeText className="text-[12px] text-muted">
            {stats.flowing}/{stats.live}
          </CodeText>
          <MicroLabel>{shown.length} ta</MicroLabel>
        </span>
      </div>

      {/* Devor — yoyilgan panel ichida siljish ruxsat etilgan. */}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-1.5">
        {shown.length === 0 ? (
          <div className="intel-grid flex h-full min-h-[40vh] items-center justify-center rounded-[4px] border border-dashed border-border">
            <MicroLabel>{error ? 'Aloqa yo‘q' : loading ? 'Yuklanmoqda' : 'Topilmadi'}</MicroLabel>
          </div>
        ) : (
          <motion.div
            variants={stagger}
            initial="hidden"
            animate="show"
            className="grid gap-1.5"
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
          >
            {shown.map((camera, index) => {
              const focused = camera.id === focusId;
              // Oqim faqat BIRINCHI `layout` ta katakda (ular eng
              // "gapiradiganlari — rankCameras). Qolganlari kadr
              // ko'rsatadi: ro'yxat uzun bo'lsa ham ulanishlar soni
              // tanlangan setkadan oshmaydi.
              const playing =
                pageVisible && !focusId && index < layout && isStreaming(camera);
              if (focused) {
                // Kattalashtirilganda katak o'rni bo'sh qoladi: aynan shu
                // element yuqorida `layoutId` bilan qayta tug'iladi.
                return <div key={camera.id} className="intel-grid aspect-video rounded-[4px] opacity-40" />;
              }
              return (
                <CameraTile
                  key={camera.id}
                  camera={camera}
                  code={cameraCode(codes, camera.id)}
                  index={index}
                  playing={playing}
                  layoutId={`camera-tile-${camera.id}`}
                  onSelect={() => setFocusId(camera.id)}
                  onStreamUnavailable={onStreamUnavailable}
                />
              );
            })}
          </motion.div>
        )}
      </div>

      <AnimatePresence>
        {focus && (
          <motion.div
            key="focus"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: EASE }}
            className="absolute inset-0 z-30 flex flex-col bg-white/80 p-2 backdrop-blur-[2px] sm:p-3"
          >
            <FocusedCamera
              camera={focus}
              code={cameraCode(codes, focus.id)}
              ptz={ptzAvailable}
              playing={pageVisible}
              onClose={() => setFocusId(null)}
              onStreamUnavailable={onStreamUnavailable}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Kattalashtirilgan bitta kamera — devordagi katagidan "o'sib chiqadi". */
function FocusedCamera({
  camera,
  code,
  ptz,
  playing,
  onClose,
  onStreamUnavailable,
}: {
  camera: CameraFeed;
  code: string;
  ptz: boolean;
  playing: boolean;
  onClose: () => void;
  onStreamUnavailable: () => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const live = playing && isStreaming(camera);
  const flow = useVideoFlow(holder, live);
  const place = cameraPlaceCode(camera);
  // Yuz skaneri — faqat shu BITTA kattalashtirilgan kamerada: har so'rov
  // serverda haqiqiy kadr olish va yuz tahlili, gridning 16 katagida
  // yoqilsa server bo'g'ilardi.
  const [scan, setScan] = useState<LiveDetectionResult | null>(null);
  const counts = scanCounts(scan);
  const seen = useSeenPeople();

  return (
    <motion.div
      layoutId={`camera-tile-${camera.id}`}
      className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[6px] bg-neutral-900"
    >
      <div ref={holder} className="relative min-h-0 flex-1">
        {live ? (
          <LiveVideoPlayer
            streamUrl={camera.streamUrl}
            priority
            fit="contain"
            cameraId={camera.id}
            showDetections
            onDetection={(result) => {
              setScan(result);
              seen.add(result);
            }}
            onStreamUnavailable={onStreamUnavailable}
          />
        ) : (
          <CameraThumbnail cameraId={camera.id} alt={camera.name} className="h-full w-full" refreshMs={10_000} />
        )}
        <DegradedLayer show={live && flow === 'stalled'} />
        {!live && <StateLayer camera={camera} />}
        {live && <ScanBadge counts={counts} />}
        {live && <RecognizedRail people={seen.people} onPick={seen.pick} />}
      </div>
      <PersonQuickView person={seen.picked} onClose={seen.close} />

      <div className="flex shrink-0 items-center gap-2 bg-black/70 px-3 py-2 text-white">
        <LiveDot on={flow === 'flowing'} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{camera.name}</span>
        {place && <CodeText className="text-[11px] text-white/60">{place}</CodeText>}
        <CodeText className="text-[11px] text-white/60">{code}</CodeText>
        <button
          type="button"
          onClick={onClose}
          aria-label="Kamerani yopish"
          className="grid h-7 w-7 place-items-center rounded-[4px] text-white/70 transition-colors hover:bg-white/15 hover:text-white"
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>

      {ptz && (
        <div className="absolute end-3 top-3 z-10 w-[min(220px,45%)]">
          <PtzControls cameraId={camera.id} globalKeyboard defaultOpen={false} />
        </div>
      )}
    </motion.div>
  );
}

/** Devor/mozaika katagi. */
function CameraTile({
  camera,
  code,
  index,
  playing,
  dense = false,
  dormant = false,
  layoutId,
  onSelect,
  onStreamUnavailable,
}: {
  camera: CameraFeed;
  code: string;
  index: number;
  playing: boolean;
  dense?: boolean;
  /** Katak ekranda ko'rinmayapti (panel yoyilgan) — na oqim, na kadr
   * so'raladi: yoyilgan devor ustiga ortiqcha so'rov qo'shilmasin. */
  dormant?: boolean;
  /** Faqat devor kataklarida: kattalashtirishdagi `layoutId` morfi.
   * Yig'ilgan mozaika uni BERMAYDI — aks holda yoyilganda bir xil
   * `layoutId` ikki joyda turib qolardi. */
  layoutId?: string;
  onSelect?: () => void;
  onStreamUnavailable: () => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const flow = useVideoFlow(holder, playing);
  const place = cameraPlaceCode(camera);

  return (
    <motion.div
      layoutId={layoutId}
      variants={panelIn}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={camera.name}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (!onSelect) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        'relative min-h-0 min-w-0 overflow-hidden rounded-[4px] bg-neutral-900 outline-none',
        !dense && 'aspect-video',
        onSelect && 'cursor-pointer focus-visible:ring-2 focus-visible:ring-primary',
      )}
    >
      <div ref={holder} className="absolute inset-0">
        {dormant ? (
          <span className="intel-grid block h-full w-full bg-surface-2" />
        ) : playing && camera.streamUrl ? (
          <LiveVideoPlayer
            streamUrl={camera.streamUrl}
            priority
            // Kataklar birdaniga emas, navbat bilan ulanadi.
            startDelayMs={index * 220}
            fit="cover"
            onStreamUnavailable={onStreamUnavailable}
          />
        ) : (
          <CameraThumbnail cameraId={camera.id} alt={camera.name} className="h-full w-full" refreshMs={15_000} />
        )}
      </div>

      <DegradedLayer show={playing && flow === 'stalled'} />
      {!playing && !dormant && <StateLayer camera={camera} />}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-gradient-to-t from-black/75 to-transparent px-1.5 pb-1 pt-4 text-white">
        <LiveDot on={flow === 'flowing'} />
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium">{camera.name}</span>
        {!dense && place && <CodeText className="text-[10px] text-white/60">{place}</CodeText>}
        <CodeText className="text-[10px] text-white/60">{code}</CodeText>
      </div>
    </motion.div>
  );
}

/** Shu kamerada tanilganlar (o'ng ustun) va bosilgan karta. Kamera
 *  almashganda komponent qayta o'rnatiladi — ro'yxat ham yangidan. */
function useSeenPeople() {
  const [people, setPeople] = useState<SeenPerson[]>([]);
  const [pickedId, setPickedId] = useState<string | null>(null);
  return {
    people,
    add: (result: LiveDetectionResult | null) => setPeople((prev) => mergeSeenPeople(prev, result, Date.now())),
    picked: people.find((person) => person.id === pickedId) ?? null,
    pick: (person: SeenPerson) => setPickedId(person.id),
    close: () => setPickedId(null),
  };
}

/** Skaner natijasi: nechta yuz, nechtasi tanildi, nechtasi notanish. */
export function scanCounts(scan: LiveDetectionResult | null) {
  if (!scan) return null;
  let known = 0;
  let unknown = 0;
  let small = 0;
  for (const face of scan.faces) {
    const status = face.status ?? (face.personName ? 'tanildi' : 'notanish');
    if (status === 'tanildi') known += 1;
    else if (status === 'notanish') unknown += 1;
    else small += 1;
  }
  // Tahlil kadrining o'lchami (server asosiy oqimdan oladi) — VIDEO emas:
  // brauzerga kichik oqim (720p/432p) keladi. Ilgari bu "4K" deb yozilib,
  // video 4K da kelyapti degan noto'g'ri tasavvur berardi.
  return { total: scan.faces.length, known, unknown, small, ai: resolutionLabel(scan.frameHeight) };
}

/** Video ustidagi skaner holati — AI hozir nimani ko'rayotgani. */
function ScanBadge({ counts }: { counts: ReturnType<typeof scanCounts> }) {
  return (
    <div className="pointer-events-none absolute left-3 top-3 z-[3] flex items-center gap-2 rounded-full bg-black/65 px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur">
      <span className={cn('h-2 w-2 rounded-full', counts ? 'live-dot bg-sky-400 text-sky-400' : 'bg-white/40')} aria-hidden="true" />
      {counts ? (
        <>
          <span>Yuz {counts.total}</span>
          <span className="text-emerald-300">Tanildi {counts.known}</span>
          <span className="text-rose-300">Notanish {counts.unknown}</span>
          {counts.small > 0 && <span className="text-white/60">Kichik {counts.small}</span>}
          {counts.ai && (
            <span className="rounded bg-white/15 px-1 text-[10px]" title="Yuz tahlili server tomonda shu o'lchamdagi kadrda (video o'lchami emas)">
              Tahlil {counts.ai}
            </span>
          )}
        </>
      ) : (
        <span>Skanerlanmoqda…</span>
      )}
    </div>
  );
}

/** Nafas oluvchi nuqta — faqat kadr ROSTDAN almashayotganda. */
function LiveDot({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn('h-1.5 w-1.5 shrink-0 rounded-full', on ? 'live-dot bg-emerald-400 text-emerald-400' : 'bg-white/35')}
    />
  );
}

/** Oqim yo'qolgan katak qorayib qolmaydi: o'lchov to'ri va bitta so'z. */
function DegradedLayer({ show }: { show: boolean }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="intel-grid absolute inset-0 z-[2] grid place-items-center bg-surface-2"
        >
          <MicroLabel>Uzildi</MicroLabel>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Oqim ochilmagan katak nega jim turibdi — bir so'zda. */
function StateLayer({ camera }: { camera: CameraFeed }) {
  const word =
    camera.status !== 'live' ? 'Oflayn' : camera.hasVideo === false ? 'Tasvirsiz' : !camera.streamUrl ? 'Havolasiz' : 'Kadr';
  return (
    <span className="pointer-events-none absolute start-1.5 top-1.5 z-[2] rounded-[3px] bg-black/60 px-1.5 py-0.5">
      <MicroLabel className="!text-white/75">{word}</MicroLabel>
    </span>
  );
}

/** Asosiy (katta) kamera — jonli tasvir va yuz skaneri: kim tanildi, kim
 *  notanish, nechta yuz ko'rinmoqda. Skaner faqat shu BITTA kamerada
 *  (har so'rov serverda haqiqiy yuz tahlili). */
function StageCamera({
  camera,
  code,
  playing,
  onStreamUnavailable,
  onClose,
}: {
  camera: CameraFeed;
  code: string;
  playing: boolean;
  onStreamUnavailable: () => void;
  onClose: () => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const live = playing && isStreaming(camera);
  const flow = useVideoFlow(holder, live);
  const place = cameraPlaceCode(camera);
  const [scan, setScan] = useState<LiveDetectionResult | null>(null);
  const counts = scanCounts(scan);
  const seen = useSeenPeople();
  // "Video yuklanmoqda" pardasi: oqim orqada ulanadi, BIRINCHI KADR kelishi
  // bilan (kamida CAMERA_LOAD_MIN_MS) ochiladi. Ilgari doim 5 s turardi —
  // video odatda 1.5-2.5 s da tayyor bo'lsa ham (2026-10-06).
  const videoHeight = useVideoHeight(holder, live);
  const [openedAt] = useState(() => Date.now());
  const [loadingCover, setLoadingCover] = useState(true);
  const ready = videoHeight > 0 || !live;
  useEffect(() => {
    if (!loadingCover) return;
    const elapsed = Date.now() - openedAt;
    if (coverDone(elapsed, ready)) {
      setLoadingCover(false);
      return;
    }
    const wait = (ready ? CAMERA_LOAD_MIN_MS : CAMERA_LOAD_MS) - elapsed;
    const timer = window.setTimeout(() => setLoadingCover(false), Math.max(0, wait));
    return () => window.clearTimeout(timer);
  }, [loadingCover, ready, openedAt]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[6px] bg-neutral-900">
      <div ref={holder} className="relative min-h-0 flex-1">
        {live ? (
          <LiveVideoPlayer
            streamUrl={camera.streamUrl}
            priority
            fit="contain"
            cameraId={camera.id}
            showDetections
            onDetection={(result) => {
              setScan(result);
              seen.add(result);
            }}
            onStreamUnavailable={onStreamUnavailable}
          />
        ) : (
          <CameraThumbnail cameraId={camera.id} alt={camera.name} className="h-full w-full" refreshMs={10_000} />
        )}
        <DegradedLayer show={!loadingCover && live && flow === 'stalled'} />
        {!live && !loadingCover && <StateLayer camera={camera} />}
        {live && !loadingCover && <ScanBadge counts={counts} />}
        {live && !loadingCover && <RecognizedRail people={seen.people} onPick={seen.pick} />}
        <AnimatePresence>{loadingCover && <LoadingCover name={camera.name} place={place} />}</AnimatePresence>
      </div>
      <PersonQuickView person={seen.picked} onClose={seen.close} />
      <div className="flex shrink-0 items-center gap-2 bg-black/70 px-3 py-1.5 text-white">
        <LiveDot on={!loadingCover && flow === 'flowing'} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{camera.name}</span>
        {videoHeight > 0 && (
          <span className="shrink-0 rounded bg-white/15 px-1.5 py-px text-[10px] font-semibold tabular-nums text-white/80" title={`Video: ${videoHeight}p`}>
            {resolutionLabel(videoHeight)}
          </span>
        )}
        {place && <CodeText className="text-[11px] text-white/60">{place}</CodeText>}
        <CodeText className="text-[11px] text-white/60">{code}</CodeText>
        <button
          type="button"
          onClick={onClose}
          aria-label="Kamerani yopish"
          title="Yopish"
          className="ms-1 grid h-6 w-6 place-items-center rounded-full text-white/70 transition hover:bg-white/15 hover:text-white"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

/** Brauzer haqiqatda dekodlayotgan video balandligi (0 — hali kadr yo'q).
 *  Birinchi kadrgacha 100 ms da (pardani tez ochish uchun), keyin 2 s da
 *  tekshiriladi. */
function useVideoHeight(holder: RefObject<HTMLDivElement | null>, active: boolean): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    if (!active) return;
    let timer: number | undefined;
    const sample = () => {
      const video = holder.current?.querySelector('video');
      const current = video && video.readyState >= 2 && video.videoWidth > 0 ? video.videoHeight : 0;
      setHeight(current);
      timer = window.setTimeout(sample, current > 0 ? 2_000 : 100);
    };
    sample();
    return () => window.clearTimeout(timer);
  }, [holder, active]);
  return active ? height : 0;
}

/** Xona kartasi ustida qisqa turilsa (120 ms — sichqoncha o'tib ketayotgan
 *  bo'lsa emas) shu kameraning WebRTC ulanishi oldindan ochiladi. */
const PREWARM_HOVER_MS = 120;
function usePrewarmOnHover() {
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return {
    start: (cameraId: string) => {
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => prewarmWebrtc(cameraId), PREWARM_HOVER_MS);
    },
    cancel: () => window.clearTimeout(timer.current),
  };
}

/** Hech kamera tanlanmagan — markazda taklif (kirishda ataylab bo'sh:
 *  har ochilish = bitta jonli oqim, u faqat kerak bo'lganda ulanadi). */
function PickPlaceholder({ message, building }: { message: string | null; building: string | null }) {
  return (
    <div className="intel-grid relative flex min-h-0 flex-1 flex-col items-center justify-center gap-2 overflow-hidden rounded-[6px] border border-dashed border-border bg-surface-2/60 text-center">
      <motion.span
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.35, ease: EASE }}
        className="grid h-12 w-12 place-items-center rounded-full bg-primary-soft text-primary shadow-sm"
        aria-hidden="true"
      >
        <Video size={22} />
      </motion.span>
      <span className="text-[15px] font-semibold text-fg">{message ?? 'Kamerani tanlang'}</span>
      {!message && (
        <span className="max-w-[320px] px-4 text-[12px] leading-snug text-muted">
          {building ? `${building}: pastdan xonani tanlang` : 'Pastdan binoni, so‘ng xonani tanlang — jonli video shu yerda ochiladi'}
        </span>
      )}
    </div>
  );
}

/** Xona tanlangach — "Video yuklanmoqda" pardasi (birinchi kadrgacha). */
function LoadingCover({ name, place }: { name: string; place: string | null }) {
  return (
    <motion.div
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: EASE }}
      className="absolute inset-0 z-[4] flex flex-col items-center justify-center gap-3 bg-neutral-900 text-white"
      role="status"
      aria-live="polite"
    >
      <span className="relative grid h-14 w-14 place-items-center" aria-hidden="true">
        <motion.span
          className="absolute inset-0 rounded-full border-2 border-white/15 border-t-sky-400"
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
        />
        <Video size={20} className="text-white/80" />
      </span>
      <span className="text-[14px] font-semibold">Video yuklanmoqda…</span>
      <span className="max-w-[80%] truncate text-[12px] text-white/60">
        {name}
        {place ? ` · ${place}` : ''}
      </span>
      <span className="h-1 w-40 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
        <motion.span
          className="block h-full rounded-full bg-sky-400"
          initial={{ width: '0%' }}
          animate={{ width: '92%' }}
          transition={{ duration: CAMERA_LOAD_MS / 1000, ease: [0.1, 0.7, 0.3, 1] }}
        />
      </span>
    </motion.div>
  );
}

/** Binolar tasmasi: nomi va nechta kamera (shundan nechtasi tasvir uzatmoqda). */
function BuildingStrip({
  buildings,
  onPick,
  loading,
}: {
  buildings: ReturnType<typeof buildingCards>;
  onPick: (name: string) => void;
  loading: boolean;
}) {
  if (buildings.length === 0) {
    return (
      <div className="flex h-[78px] shrink-0 items-center justify-center rounded-[6px] border border-dashed border-border text-[12px] text-muted">
        {loading ? 'Binolar yuklanmoqda…' : 'Kamera biriktirilgan bino yo‘q'}
      </div>
    );
  }
  return (
    <div className="flex h-[78px] min-w-0 shrink-0 gap-1.5 overflow-x-auto pb-1" aria-label="Binolar">
      {buildings.map((b, index) => (
        <motion.button
          key={b.name}
          type="button"
          onClick={() => onPick(b.name)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: Math.min(index, 10) * 0.03, ease: EASE }}
          title={b.name}
          className="group flex h-full w-[168px] shrink-0 flex-col justify-between rounded-[8px] border border-border bg-surface px-2.5 py-2 text-left shadow-sm transition hover:border-primary hover:shadow-md"
        >
          <span className="flex items-start gap-2">
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-[6px] bg-primary/10 text-primary" aria-hidden="true">
              <Building2 size={14} />
            </span>
            <span className="line-clamp-2 min-w-0 flex-1 text-[12px] font-semibold leading-tight text-fg">{b.name}</span>
            <ChevronRight size={14} className="mt-0.5 shrink-0 text-subtle transition group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden="true" />
          </span>
          <span className="flex items-baseline justify-between text-[11px] text-muted">
            <span>{b.total} ta kamera</span>
            <span className="tabular-nums text-success">{b.streaming} jonli</span>
          </span>
        </motion.button>
      ))}
    </div>
  );
}

/** Xonalar (kameralar) tasmasi — faqat nomi, rasm/video yo'q; bosilsa —
 *  yuqorida yuklanish pardasi bilan jonli video. */
function RoomStrip({
  title,
  rooms,
  codes,
  activeId,
  onPick,
  onBack,
}: {
  title: string;
  rooms: CameraFeed[];
  codes: ReadonlyMap<string, string>;
  activeId: string | null;
  onPick: (id: string) => void;
  onBack: () => void;
}) {
  const hover = usePrewarmOnHover();
  return (
    <div className="flex shrink-0 flex-col gap-1">
      <div className="flex items-center gap-1.5 px-0.5">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex h-6 items-center gap-1 rounded-full border border-border bg-surface px-2 text-[11px] font-medium text-muted transition hover:border-primary hover:text-primary"
        >
          <ArrowLeft size={12} aria-hidden="true" /> Binolar
        </button>
        <span className="min-w-0 truncate text-[12px] font-semibold text-fg">{title}</span>
        <span className="ms-auto shrink-0 whitespace-nowrap text-[11px] tabular-nums text-muted">{rooms.length} ta xona</span>
      </div>
      {rooms.length === 0 ? (
        <div className="flex h-[62px] items-center justify-center rounded-[6px] border border-dashed border-border text-[12px] text-muted">
          Mos kamera topilmadi
        </div>
      ) : (
        <div className="flex h-[62px] min-w-0 gap-1.5 overflow-x-auto pb-1" aria-label="Xonalar">
          {rooms.map((camera) => {
            const on = camera.id === activeId;
            const streaming = isStreaming(camera);
            const floor = typeof camera.floor === 'number' ? `${camera.floor}-qavat` : null;
            return (
              <button
                key={camera.id}
                type="button"
                onClick={() => onPick(camera.id)}
                // Ustida turilganda ulanish oldindan boshlanadi (lib/webrtcStream.ts).
                onPointerEnter={() => streaming && hover.start(camera.id)}
                onPointerLeave={hover.cancel}
                onFocus={() => streaming && hover.start(camera.id)}
                aria-pressed={on}
                title={streaming ? camera.name : `${camera.name} — hozir tasvir yo‘q`}
                className={cn(
                  'flex h-full w-[150px] shrink-0 flex-col justify-between rounded-[8px] border px-3 py-1.5 text-left transition',
                  on
                    ? 'border-primary bg-primary-soft shadow-sm'
                    : 'border-border bg-surface hover:border-primary hover:shadow-sm',
                  !streaming && 'opacity-70',
                )}
              >
                <span className="line-clamp-2 text-[12px] font-semibold leading-tight text-fg">{camera.name}</span>
                <span className="flex items-center gap-1.5 text-[10px] text-muted">
                  <span
                    className={cn('h-1.5 w-1.5 shrink-0 rounded-full', streaming ? 'bg-success' : 'bg-subtle')}
                    aria-hidden="true"
                  />
                  <span className="truncate">{[floor, cameraCode(codes, camera.id)].filter(Boolean).join(' · ')}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
