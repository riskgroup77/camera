import { useEffect, useMemo, useState } from 'react';
import { Building2, ChevronRight, GripVertical, Layers, ListVideo, Plus, RefreshCw, X } from 'lucide-react';
import { CodeText, IconButton, MicroLabel, SearchInput, Skeleton, StatusLamp, Tabs, cn, focusRing, type IntelStatus } from '../../ui';
import {
  buildingGroups,
  floorGroups,
  isCameraOnline,
  type CameraGroup,
  type WallCameraFilters,
  type WallStatusFilter,
} from '../../lib/videoWall';
import type { CameraFeed } from '../../types';
import { UNKNOWN_CAMERA_CODE, cameraPlaceCode } from './cameraCode';
import { DRAG_CAMERA } from './WallTile';

/** Ro'yxat juda uzun bo'lsa DOM'ni og'irlashtirmaslik uchun — qidiruv
 * bilan toraytirish taklif qilinadi. */
const MAX_ROWS = 300;

const STATUS_TABS: Array<{ id: WallStatusFilter; label: string }> = [
  { id: 'all', label: 'Hammasi' },
  { id: 'live', label: 'Tasvir bor' },
  { id: 'offline', label: "Tasvir yo'q" },
];

/** Videodevorning yon paneli — kamera tanlagich.
 *
 * Ikki yo'l bitta panelda:
 * - daraxt: bino → qavat → kamera (avval alohida "Bino va qavat bo'yicha"
 *   ekrani edi; ikkala ekran ham oxir-oqibat jonli kamera ochardi);
 * - qidiruv/holat filtri — nom, zona yoki bino bo'yicha, daraxtning
 *   qaysi darajasida turganidan qat'i nazar.
 *
 * Ko'rinishi — texnik ko'rsatkich: chap tomonda monoshrift kodlar ustuni,
 * guruh sarlavhalari bosh harfda va ingichka chiziq bilan, qatorlar zich
 * va 1px chiziq bilan ajratilgan.
 *
 * Tanlov `WallCameraFilters`da turadi, shuning uchun devorning "Ro'yxat"
 * rejimi ham aynan shu ro'yxat bo'yicha sahifalaydi. */
export default function CameraSidebar({
  cameras,
  filtered,
  filters,
  onFiltersChange,
  onAdd,
  onClose,
  onReload,
  loading,
  error,
  onWall,
  codes,
  className,
}: {
  cameras: CameraFeed[];
  filtered: CameraFeed[];
  filters: WallCameraFilters;
  onFiltersChange: (next: WallCameraFilters) => void;
  onAdd: (camera: CameraFeed) => void;
  onClose: () => void;
  onReload: () => void;
  loading: boolean;
  error: string | null;
  /** Hozir devorda turgan kameralar — ro'yxatda belgilanadi. */
  onWall: ReadonlySet<string>;
  /** Kamera xizmat kodlari (`buildCameraCodes`). */
  codes?: ReadonlyMap<string, string>;
  className?: string;
}) {
  const onlineCount = useMemo(() => cameras.filter(isCameraOnline).length, [cameras]);
  const set = (patch: Partial<WallCameraFilters>) => onFiltersChange({ ...filters, ...patch });

  // "Barcha kameralar" — qavatni tanlamay turib binoning butun ro'yxatini
  // ko'rish. Bino almashsa daraxtga qaytamiz.
  const [flat, setFlat] = useState(false);
  useEffect(() => setFlat(false), [filters.building]);

  const searching = filters.search.trim().length > 0;
  const buildings = useMemo(() => buildingGroups(cameras, filters), [cameras, filters]);
  const floors = useMemo(() => (filters.building ? floorGroups(cameras, filters) : []), [cameras, filters]);
  const level: 'binolar' | 'qavatlar' | 'kameralar' =
    searching || flat || filters.floor ? 'kameralar' : filters.building ? 'qavatlar' : 'binolar';

  const crumbClass = (current: boolean) =>
    cn(
      'intel-code rounded-[2px] px-1.5 py-0.5 text-[11px] transition-colors',
      focusRing,
      current ? 'bg-primary-soft text-primary' : 'text-muted hover:bg-surface-2 hover:text-fg',
    );

  const groupRow = (group: CameraGroup, icon: typeof Building2, onOpen: () => void) => {
    const Icon = icon;
    return (
      <li key={group.key || 'yoq'} className="border-b border-border last:border-b-0">
        <button
          type="button"
          onClick={onOpen}
          className={cn('group flex w-full items-center gap-2 px-1.5 py-2 text-left transition-colors hover:bg-surface-2', focusRing)}
        >
          <Icon size={14} aria-hidden="true" className="shrink-0 text-subtle group-hover:text-fg" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{group.label}</span>
            <span className="mt-0.5 flex items-center gap-2">
              <CodeText className="text-[10px] text-subtle">{group.total} ta kamera</CodeText>
              <CodeText className="text-[10px] text-success">{group.online} tasi tasvir bermoqda</CodeText>
            </span>
          </span>
          <ChevronRight size={14} aria-hidden="true" className="shrink-0 text-subtle group-hover:text-fg" />
        </button>
      </li>
    );
  };

  /** Guruh sarlavhasi: bosh harfli yorliq + ingichka chiziq + son. */
  const sectionHead = (label: string, count: number, hint: string) => (
    <div className="flex items-center gap-2">
      <MicroLabel className="!text-fg">{label}</MicroLabel>
      <span aria-hidden="true" className="h-px flex-1 bg-border" />
      <CodeText className="text-[10px] text-muted">{count}</CodeText>
      <MicroLabel className="hidden sm:inline">{hint}</MicroLabel>
    </div>
  );

  return (
    <aside
      aria-label="Kameralar"
      className={cn('intel-panel flex h-full w-full shrink-0 flex-col gap-2 overflow-hidden p-2.5 text-fg md:w-72', className)}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
        <div className="min-w-0">
          <MicroLabel className="!text-fg">Kameralar ko&apos;rsatkichi</MicroLabel>
          <p className="intel-code mt-0.5 text-[11px] text-muted">
            {cameras.length} ta · <span className="text-success">{onlineCount} tasi tasvir bermoqda</span>
          </p>
        </div>
        <div className="-mr-1 flex items-center">
          <IconButton icon={RefreshCw} size="sm" label="Ro'yxatni yangilash" onClick={onReload} loading={loading && cameras.length > 0} />
          <IconButton icon={X} size="sm" label="Yon panelni yopish" onClick={onClose} />
        </div>
      </div>

      <div className="flex items-center gap-2 border-b border-border pb-2">
        <MicroLabel className="shrink-0">Filtr</MicroLabel>
        <SearchInput
          size="sm"
          value={filters.search}
          onChange={(search) => set({ search })}
          placeholder="Nom, zona yoki bino..."
          ariaLabel="Kameralarni qidirish"
          className="min-w-0 flex-1 sm:max-w-none"
        />
      </div>

      <nav aria-label="Bino va qavat" className="flex flex-wrap items-center gap-0.5">
        <button
          type="button"
          aria-current={level === 'binolar' ? 'page' : undefined}
          onClick={() => {
            setFlat(false);
            set({ building: '', floor: '' });
          }}
          className={crumbClass(level === 'binolar')}
        >
          Barcha binolar
        </button>
        {filters.building && (
          <>
            <ChevronRight size={12} aria-hidden="true" className="text-subtle" />
            <button
              type="button"
              aria-current={level === 'qavatlar' ? 'page' : undefined}
              onClick={() => {
                setFlat(false);
                set({ floor: '' });
              }}
              className={crumbClass(level === 'qavatlar')}
            >
              {filters.building}
            </button>
          </>
        )}
        {filters.building && filters.floor && (
          <>
            <ChevronRight size={12} aria-hidden="true" className="text-subtle" />
            <span aria-current="page" className={crumbClass(true)}>
              {floors.find((floor) => floor.key === filters.floor)?.label ?? filters.floor}
            </span>
          </>
        )}
      </nav>

      <Tabs
        variant="segmented"
        size="sm"
        ariaLabel="Holat"
        tabs={STATUS_TABS}
        value={filters.status}
        onChange={(status) => set({ status })}
        className="w-full [&>button]:flex-1 [&>button]:justify-center"
      />

      {error && <p role="alert" className="rounded-[2px] border border-danger/30 bg-danger-soft px-2 py-1.5 text-[11px] text-danger">{error}</p>}

      {level === 'binolar'
        ? sectionHead('Binolar', buildings.length, 'binoni tanlang')
        : level === 'qavatlar'
          ? sectionHead('Qavatlar', floors.length, 'qavatni tanlang')
          : sectionHead('Kameralar', filtered.length, 'katakka torting')}

      {/* Sinovlar va yordamchi matn uchun — daraja izohi. */}
      <p className="sr-only">
        {level === 'binolar'
          ? `${buildings.length} ta bino · binoni tanlang`
          : level === 'qavatlar'
            ? `${floors.length} ta qavat · qavatni tanlang`
            : `${filtered.length} ta mos keldi · katakka torting yoki bosing`}
      </p>

      <ul className="-mx-0.5 min-h-0 flex-1 overflow-y-auto px-0.5">
        {loading && cameras.length === 0 &&
          Array.from({ length: 8 }).map((_, index) => (
            <li key={index} className="py-0.5">
              <Skeleton className="h-8 w-full" />
            </li>
          ))}

        {level !== 'kameralar' && (
          <li className="border-b border-border">
            <button
              type="button"
              onClick={() => setFlat(true)}
              className={cn('flex w-full items-center gap-2 px-1.5 py-2 text-left text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg', focusRing)}
            >
              <ListVideo size={14} aria-hidden="true" className="shrink-0" />
              {level === 'qavatlar' ? 'Binodagi barcha kameralar' : 'Barcha kameralar'}
              <CodeText className="ml-auto text-[10px] text-subtle">{filtered.length}</CodeText>
            </button>
          </li>
        )}

        {level === 'binolar' &&
          buildings.map((group) =>
            groupRow(group, Building2, () => {
              setFlat(false);
              set({ building: group.key, floor: '' });
            }),
          )}

        {level === 'qavatlar' && floors.map((group) => groupRow(group, Layers, () => set({ floor: group.key })))}

        {level === 'kameralar' &&
          filtered.slice(0, MAX_ROWS).map((camera) => {
            const online = isCameraOnline(camera);
            const noVideo = camera.status === 'live' && camera.hasVideo === false;
            const placed = onWall.has(camera.id);
            const tone: IntelStatus = online ? 'ok' : noVideo ? 'warn' : 'idle';
            const place = cameraPlaceCode(camera);
            return (
              <li key={camera.id} className="border-b border-border last:border-b-0">
                <button
                  type="button"
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData(DRAG_CAMERA, camera.id);
                    event.dataTransfer.effectAllowed = 'copy';
                  }}
                  onClick={() => onAdd(camera)}
                  title={`${camera.name} — bosing: devorga qo'shish, torting: kerakli katakka`}
                  className={cn(
                    'group flex w-full cursor-grab items-center gap-2 px-1 py-1.5 text-left transition-colors active:cursor-grabbing focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-primary/40',
                    placed ? 'bg-primary-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <GripVertical size={12} aria-hidden="true" className="shrink-0 text-subtle opacity-50 group-hover:opacity-100" />
                  <CodeText className="w-[52px] shrink-0 text-[10px] font-semibold text-muted">
                    {codes?.get(camera.id) ?? UNKNOWN_CAMERA_CODE}
                  </CodeText>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-medium leading-tight">{camera.name}</span>
                    <span className="mt-0.5 flex items-center gap-1.5">
                      {place && <CodeText className="shrink-0 text-[10px] text-subtle">{place}</CodeText>}
                      <MicroLabel className="truncate">
                        {[camera.building, camera.floor != null ? `${camera.floor}-qavat` : null, camera.zone]
                          .filter(Boolean)
                          .join(' · ')}
                      </MicroLabel>
                    </span>
                  </span>
                  {/* Chiroq — yorlig'i faqat ekran o'quvchi uchun: qator zich. */}
                  <StatusLamp
                    status={tone}
                    label={online ? 'Tasvir bor' : noVideo ? 'Tasvirsiz' : 'Signalsiz'}
                    className="shrink-0 [&>.intel-micro]:sr-only"
                  />
                  {placed ? (
                    <MicroLabel className="shrink-0 !text-primary">Devorda</MicroLabel>
                  ) : (
                    <Plus size={14} aria-hidden="true" className="shrink-0 text-subtle group-hover:text-fg" />
                  )}
                </button>
              </li>
            );
          })}

        {level === 'kameralar' && filtered.length > MAX_ROWS && (
          <li className="px-2 py-1.5 text-center text-[11px] text-muted">
            Yana {filtered.length - MAX_ROWS} ta — qidiruv yoki filtr bilan toraytiring
          </li>
        )}
        {!loading && level === 'kameralar' && filtered.length === 0 && (
          <li className="px-2 py-8 text-center text-[12px] text-muted">
            {cameras.length === 0 ? "Kameralar ro'yxati bo'sh" : 'Mos kamera topilmadi'}
          </li>
        )}
        {!loading && level === 'binolar' && buildings.length === 0 && (
          <li className="px-2 py-8 text-center text-[12px] text-muted">
            {cameras.length === 0 ? "Kameralar ro'yxati bo'sh" : 'Mos bino topilmadi'}
          </li>
        )}
      </ul>
    </aside>
  );
}
