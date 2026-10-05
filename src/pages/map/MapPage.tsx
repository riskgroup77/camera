import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, ImageUp, Map as MapIcon, MonitorPlay, Pencil, Siren, Trash2, X } from 'lucide-react';
import { Button, ButtonLink, Card, EmptyState, ErrorState, IconButton, Page, Select, Skeleton, StatusDot, cn, useToast, type Tone } from '../../ui';
import LiveVideoPlayer from '../../components/LiveVideoPlayer';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { useVisibleInterval } from '../../lib/useVisibleInterval';
import {
  getMapBuildings,
  getMapFloor,
  placeCamera,
  uploadMapImage,
  type MapBuilding,
  type MapCamera,
  type MapCameraStatus,
  type MapFloorView,
  type MapPlacement,
} from '../../lib/xaritaApi';
import FloorMapCanvas, { DRAG_MIME, STATUS_STYLE } from './FloorMapCanvas';
import { normalizeAngle, type Point } from './mapGeometry';

/**
 * XARITA — qavat rejasi ustida kameralar (Milestone Smart Map kabi).
 *
 * Operator binoni va qavatni tanlaydi, rejada kameralar holati (rang),
 * qarash yo'nalishi (konus) va ochiq hodisalar (qizil halqa) ko'rinadi.
 * Kamera bosilsa — yonda jonli ko'rinish. Tahrir rejimida (faqat
 * editCameraLocation) reja rasmi yuklanadi, kameralar sudrab qo'yiladi va
 * buriladi; har harakat darhol saqlanadi — alohida "Saqlash" unutilmaydi.
 */

const REFRESH_MS = 30_000;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

const STATUS_TONE: Record<MapCameraStatus, Tone> = { online: 'success', novideo: 'warning', offline: 'neutral' };

function pickFloor(building: MapBuilding | undefined, wanted: number | null): number | null {
  if (!building || !building.floors.length) return null;
  if (wanted != null && building.floors.some((f) => f.floor === wanted)) return wanted;
  return (building.floors.find((f) => f.hasPlan) ?? building.floors.find((f) => f.cameraCount) ?? building.floors[0]).floor;
}

export default function MapPage() {
  const toast = useToast();
  const { role } = useAuth();
  const { can } = usePermissions();
  const canEdit = can('editCameraLocation', role);
  const [params, setParams] = useSearchParams();

  const [buildings, setBuildings] = useState<MapBuilding[] | null>(null);
  const [buildingsError, setBuildingsError] = useState<string | null>(null);
  const [view, setView] = useState<MapFloorView | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [loadingView, setLoadingView] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadBuildings = useCallback(() => {
    getMapBuildings()
      .then((rows) => {
        setBuildings(rows);
        setBuildingsError(null);
      })
      .catch((err) => setBuildingsError((err as Error).message));
  }, []);
  useEffect(loadBuildings, [loadBuildings]);

  const building = buildings?.find((b) => b.id === params.get('bino')) ?? buildings?.[0];
  const rawFloor = params.get('qavat');
  const floor = pickFloor(building, rawFloor != null && rawFloor !== '' ? Number(rawFloor) : null);

  const select = (buildingId: string, nextFloor: number | null) => {
    const next = new URLSearchParams(params);
    next.set('bino', buildingId);
    if (nextFloor == null) next.delete('qavat');
    else next.set('qavat', String(nextFloor));
    setParams(next, { replace: true });
    setSelectedId(null);
  };

  const buildingId = building?.id ?? null;
  const loadView = useCallback(
    (signal?: AbortSignal, quiet = false) => {
      if (!buildingId || floor == null) return;
      if (!quiet) setLoadingView(true);
      getMapFloor(buildingId, floor, { signal })
        .then((data) => {
          setView(data);
          setViewError(null);
        })
        .catch((err) => !isAbortError(err) && setViewError((err as Error).message))
        .finally(() => !signal?.aborted && setLoadingView(false));
    },
    [buildingId, floor],
  );

  useEffect(() => {
    setView(null);
    const controller = new AbortController();
    loadView(controller.signal);
    return () => controller.abort();
  }, [loadView]);

  // Tahrir paytida fon yangilanishi sudralayotgan markerni joyidan sakratardi.
  useVisibleInterval(() => loadView(undefined, true), editing ? null : REFRESH_MS);

  const cameras = useMemo(() => view?.cameras ?? [], [view]);
  const unplaced = useMemo(
    () => [...cameras.filter((c) => c.x == null), ...(view?.candidates ?? [])],
    [cameras, view?.candidates],
  );
  const selected = cameras.find((c) => c.id === selectedId) ?? null;
  const openTotal = cameras.reduce((sum, c) => sum + c.openEvents, 0);

  // ── Tahrir ────────────────────────────────────────────────────────────
  const place = async (camera: MapCamera, body: Omit<MapPlacement, 'buildingId' | 'floor'>) => {
    if (!view) return;
    // Optimistik: marker darhol yangi joyda; xato bo'lsa serverdagi holat qaytadi.
    const updated: MapCamera = { ...camera, x: body.x, y: body.y, angle: body.angle ?? null, fov: body.fov ?? camera.fov, assigned: true };
    setView({
      ...view,
      cameras: [...view.cameras.filter((c) => c.id !== camera.id), updated].sort((a, b) => a.name.localeCompare(b.name, 'uz')),
      candidates: view.candidates.filter((c) => c.id !== camera.id),
    });
    try {
      const saved = await placeCamera(camera.id, { ...body, buildingId: view.buildingId, floor: view.floor });
      setView((current) => current && { ...current, cameras: current.cameras.map((c) => (c.id === saved.id ? saved : c)) });
      if (!camera.assigned) loadBuildings();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Saqlab bo‘lmadi');
      loadView(undefined, true);
    }
  };

  const findCamera = (id: string) => cameras.find((c) => c.id === id) ?? view?.candidates.find((c) => c.id === id);

  const moveCamera = (id: string, point: Point) => {
    const camera = findCamera(id);
    if (!camera || (camera.x === point.x && camera.y === point.y)) return;
    void place(camera, { x: point.x, y: point.y, angle: camera.angle ?? 0, fov: camera.fov });
  };

  const rotateCamera = (id: string, angle: number) => {
    const camera = findCamera(id);
    if (!camera || camera.x == null || camera.angle === angle) return;
    void place(camera, { x: camera.x, y: camera.y, angle: normalizeAngle(angle), fov: camera.fov });
  };

  const setFov = (camera: MapCamera, fov: number) => {
    if (camera.x == null || fov === camera.fov) return;
    void place(camera, { x: camera.x, y: camera.y, angle: camera.angle ?? 0, fov });
  };

  const unplace = (camera: MapCamera) => {
    setSelectedId(null);
    void place(camera, { x: null, y: null });
  };

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !view) return;
    if (!/^image\/(png|jpeg)$/.test(file.type)) return toast.error('Faqat PNG yoki JPG');
    if (file.size > MAX_IMAGE_BYTES) return toast.error('Rasm 10 MB dan katta');
    setUploading(true);
    try {
      const plan = await uploadMapImage(view.buildingId, view.floor, file);
      setView((current) => current && { ...current, plan });
      loadBuildings();
      toast.success('Reja saqlandi');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Yuklab bo‘lmadi');
    } finally {
      setUploading(false);
    }
  };

  const uploadButton = (
    <Button size="sm" icon={ImageUp} loading={uploading} onClick={() => fileRef.current?.click()}>
      {view?.plan ? 'Rejani almashtirish' : 'Reja yuklash'}
    </Button>
  );

  // ── Ko'rinish ─────────────────────────────────────────────────────────
  const plan = view?.plan?.imageUrl ? { ...view.plan, imageUrl: view.plan.imageUrl } : null;

  let body;
  if (buildingsError) body = <ErrorState message={buildingsError} onRetry={loadBuildings} />;
  else if (!buildings) body = <Skeleton className="h-[60vh] w-full" />;
  else if (!building || floor == null)
    body = (
      <Card padding="lg">
        <EmptyState icon={MapIcon} title="Binolar yo‘q" description="Kameralarga bino va qavat biriktirilgach shu yerda chiqadi" />
      </Card>
    );
  else
    body = (
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card padding="sm" className="h-[calc(100vh-190px)] min-h-[360px] overflow-hidden">
          {viewError ? (
            <ErrorState message={viewError} onRetry={() => loadView()} />
          ) : !view ? (
            <Skeleton className="h-full w-full" />
          ) : plan ? (
            <FloorMapCanvas
              plan={plan}
              cameras={cameras}
              selectedId={selectedId}
              editing={editing}
              onSelect={setSelectedId}
              onMove={moveCamera}
              onRotate={rotateCamera}
              onDropCamera={moveCamera}
            />
          ) : (
            <div className="grid h-full place-items-center">
              <EmptyState
                icon={MapIcon}
                title={view.plan ? 'Rejani ochib bo‘lmadi' : 'Reja yuklanmagan'}
                description={canEdit ? 'PNG yoki JPG, 10 MB gacha' : 'Administrator qavat rejasini yuklashi kerak'}
                action={canEdit ? uploadButton : undefined}
              />
            </div>
          )}
        </Card>

        <Card padding="none" className="flex max-h-[calc(100vh-190px)] min-h-[240px] flex-col overflow-hidden">
          {editing ? (
            <EditPanel
              camera={selected}
              unplaced={unplaced}
              hasPlan={Boolean(plan)}
              onRotate={(camera, angle) => rotateCamera(camera.id, angle)}
              onFov={setFov}
              onUnplace={unplace}
            />
          ) : selected ? (
            <CameraPanel camera={selected} onClose={() => setSelectedId(null)} />
          ) : (
            <CameraList cameras={cameras} loading={loadingView && !view} openTotal={openTotal} onSelect={setSelectedId} />
          )}
        </Card>
      </div>
    );

  return (
    <Page
      title="Xarita"
      breadcrumbs={[{ label: 'Nazorat', to: '/' }, { label: 'Xarita' }]}
      actions={
        buildings && building && floor != null ? (
          <div className="flex flex-wrap items-center gap-2">
            <Select
              size="sm"
              ariaLabel="Bino"
              value={building.id}
              onChange={(id) => select(id, pickFloor(buildings.find((b) => b.id === id), null))}
              options={buildings.map((b) => ({ value: b.id, label: b.name }))}
            />
            <span className="flex items-center rounded-control bg-surface-2 p-0.5" role="group" aria-label="Qavat">
              {building.floors.map((f) => (
                <button
                  key={f.floor}
                  type="button"
                  aria-pressed={f.floor === floor}
                  onClick={() => select(building.id, f.floor)}
                  title={`${f.floor}-qavat · ${f.cameraCount} kamera`}
                  className={cn(
                    'h-7 min-w-7 rounded-[6px] px-2 text-[12px] font-semibold tabular-nums',
                    f.floor === floor ? 'bg-surface text-fg shadow-sm' : f.hasPlan || f.cameraCount ? 'text-muted hover:text-fg' : 'text-subtle hover:text-fg',
                  )}
                >
                  {f.floor}
                </button>
              ))}
            </span>
            {canEdit && editing && view?.plan && uploadButton}
            {canEdit && (
              <Button size="sm" variant={editing ? 'primary' : 'secondary'} icon={editing ? Check : Pencil} onClick={() => setEditing((v) => !v)}>
                {editing ? 'Tayyor' : 'Tahrirlash'}
              </Button>
            )}
            <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="hidden" onChange={(e) => void onFile(e)} />
          </div>
        ) : null
      }
    >
      {body}
    </Page>
  );
}

function EventsLink({ count, cameraId }: { count: number; cameraId?: string }) {
  if (!count) return null;
  const to = cameraId ? `/hodisalar?korinish=navbat&kamera=${encodeURIComponent(cameraId)}` : '/hodisalar';
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-[12px] font-semibold text-danger hover:underline">
      <Siren size={13} aria-hidden="true" />
      {count} ochiq hodisa
    </Link>
  );
}

function CameraList({ cameras, loading, openTotal, onSelect }: { cameras: MapCamera[]; loading: boolean; openTotal: number; onSelect: (id: string) => void }) {
  return (
    <>
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <h2 className="text-[13px] font-bold">Kameralar · {cameras.length}</h2>
        <EventsLink count={openTotal} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {loading ? (
          <div className="space-y-1 p-1">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : !cameras.length ? (
          <p className="p-3 text-[13px] text-muted">Bu qavatda kamera yo‘q</p>
        ) : (
          cameras.map((camera) => (
            <button
              key={camera.id}
              type="button"
              onClick={() => onSelect(camera.id)}
              className="flex w-full items-center gap-2 rounded-control px-2.5 py-1.5 text-left hover:bg-surface-2"
            >
              <StatusDot tone={STATUS_TONE[camera.status]} label={STATUS_STYLE[camera.status].label} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{camera.name}</span>
              {camera.x == null && <span className="text-[11px] text-subtle">rejada yo‘q</span>}
              {(camera.peopleNow ?? 0) > 0 && (
                <span className="text-[12px] tabular-nums text-primary" title="So‘nggi 10 daqiqada tanilgan odamlar">
                  {camera.peopleNow} kishi
                </span>
              )}
              {camera.openEvents > 0 && <span className="text-[12px] font-bold tabular-nums text-danger">{camera.openEvents}</span>}
            </button>
          ))
        )}
      </div>
    </>
  );
}

function CameraPanel({ camera, onClose }: { camera: MapCamera; onClose: () => void }) {
  const id = encodeURIComponent(camera.id);
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[14px] font-bold">{camera.name}</h2>
          <p className="flex items-center gap-1.5 text-[12px] text-muted">
            <StatusDot tone={STATUS_TONE[camera.status]} />
            {STATUS_STYLE[camera.status].label}
            {camera.zone && <span className="truncate">· {camera.zone}</span>}
          </p>
        </div>
        <IconButton icon={X} label="Yopish" size="sm" variant="ghost" onClick={onClose} />
      </div>
      <div className="relative aspect-video overflow-hidden rounded-control bg-black">
        {camera.streamUrl && camera.status !== 'offline' ? (
          <LiveVideoPlayer key={camera.id} streamUrl={camera.streamUrl} priority fit="contain" className="h-full w-full" />
        ) : (
          <span className="grid h-full place-items-center text-[12px] text-white/60">Kamera oflayn</span>
        )}
      </div>
      <p className="text-[12px] text-muted">
        So‘nggi 10 daqiqada: <b className="text-fg">{camera.peopleNow ?? 0}</b> kishi tanildi
      </p>
      <EventsLink count={camera.openEvents} cameraId={camera.id} />
      <ButtonLink size="sm" icon={MonitorPlay} to={`/videodevor?kamera=${id}`}>
        Videodevorda ochish
      </ButtonLink>
    </div>
  );
}

interface EditPanelProps {
  camera: MapCamera | null;
  unplaced: MapCamera[];
  hasPlan: boolean;
  onRotate: (camera: MapCamera, angle: number) => void;
  onFov: (camera: MapCamera, fov: number) => void;
  onUnplace: (camera: MapCamera) => void;
}

function EditPanel({ camera, unplaced, hasPlan, onRotate, onFov, onUnplace }: EditPanelProps) {
  return (
    <>
      {camera && camera.x != null && (
        <div className="flex flex-col gap-2 border-b border-border p-3">
          <h2 className="truncate text-[13px] font-bold">{camera.name}</h2>
          <div className="grid grid-cols-2 gap-2">
            <NumberField key={`a-${camera.id}-${camera.angle}`} label="Yo‘nalish°" value={camera.angle ?? 0} min={0} max={359} onCommit={(v) => onRotate(camera, v)} />
            <NumberField key={`f-${camera.id}-${camera.fov}`} label="Ko‘lam°" value={camera.fov} min={10} max={360} onCommit={(v) => onFov(camera, v)} />
          </div>
          <Button size="sm" variant="ghost" icon={Trash2} onClick={() => onUnplace(camera)}>
            Rejadan olish
          </Button>
        </div>
      )}
      <h2 className="border-b border-border px-3 py-2.5 text-[13px] font-bold">Joylanmagan · {unplaced.length}</h2>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {!hasPlan ? (
          <p className="p-3 text-[13px] text-muted">Avval reja yuklang</p>
        ) : !unplaced.length ? (
          <p className="p-3 text-[13px] text-muted">Hammasi joylangan</p>
        ) : (
          unplaced.map((c) => (
            <div
              key={c.id}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(DRAG_MIME, c.id);
                event.dataTransfer.effectAllowed = 'move';
              }}
              className="flex cursor-grab items-center gap-2 rounded-control px-2.5 py-1.5 hover:bg-surface-2 active:cursor-grabbing"
              title="Rejaga sudrang"
            >
              <StatusDot tone={STATUS_TONE[c.status]} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{c.name}</span>
              {!c.assigned && <span className="text-[11px] text-subtle">qavatsiz</span>}
            </div>
          ))
        )}
      </div>
    </>
  );
}

function NumberField({ label, value, min, max, onCommit }: { label: string; value: number; min: number; max: number; onCommit: (value: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  const commit = () => {
    const n = Math.round(Number(draft));
    if (!Number.isFinite(n) || n < min || n > max) return setDraft(String(value));
    if (n !== value) onCommit(n);
  };
  return (
    <label className="flex flex-col gap-1 text-[11px] font-semibold text-muted">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === 'Enter' && commit()}
        className="h-8 rounded-control border border-border bg-surface px-2 text-[13px] text-fg tabular-nums"
      />
    </label>
  );
}
