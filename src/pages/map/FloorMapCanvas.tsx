import { useEffect, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { cn } from '../../ui';
import type { MapCamera, MapCameraStatus, MapPlan } from '../../lib/xaritaApi';
import { angleBetween, conePath, coneRadius, fitSize, polar, toNormalized, toPixels, type Point, type Size } from './mapGeometry';

/** Holat ranglari devor bilan bir xil ma'noda: yashil — tasvir bor,
 *  sariq — tarmoqda, lekin kadr yo'q, kulrang — javob bermayapti.
 *  Qizil faqat ochiq hodisa halqasi uchun qoldirilgan — ko'z unga tushsin. */
export const STATUS_STYLE: Record<MapCameraStatus, { dot: string; cone: string; label: string }> = {
  online: { dot: 'fill-success', cone: 'fill-success/15 stroke-success/50', label: 'Jonli' },
  novideo: { dot: 'fill-warning', cone: 'fill-warning/15 stroke-warning/50', label: 'Tasvir yo‘q' },
  offline: { dot: 'fill-subtle', cone: 'fill-subtle/10 stroke-subtle/40', label: 'Oflayn' },
};

/** Sudrab qo'yilayotgan kamera identifikatori (HTML drag-and-drop). */
export const DRAG_MIME = 'application/x-camera-id';

const DOT_R = 7;
const HANDLE_GAP = 1.15;

type Drag = { id: string; mode: 'move'; point: Point } | { id: string; mode: 'rotate'; angle: number };

interface FloorMapCanvasProps {
  plan: MapPlan & { imageUrl: string };
  cameras: MapCamera[];
  selectedId: string | null;
  editing: boolean;
  onSelect: (id: string | null) => void;
  onMove: (id: string, point: Point) => void;
  onRotate: (id: string, angle: number) => void;
  onDropCamera: (id: string, point: Point) => void;
}

export default function FloorMapCanvas({ plan, cameras, selectedId, editing, onSelect, onMove, onRotate, onDropCamera }: FloorMapCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [box, setBox] = useState<Size>({ width: 0, height: 0 });
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const update = () => setBox({ width: el.clientWidth, height: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const size = fitSize(box, { width: plan.width, height: plan.height });
  const radius = coneRadius(size);

  const pointFromEvent = (clientX: number, clientY: number): Point | null => {
    const rect = svgRef.current?.getBoundingClientRect();
    return rect ? toNormalized(clientX, clientY, rect) : null;
  };

  const startDrag = (event: ReactPointerEvent, camera: MapCamera, mode: Drag['mode']) => {
    if (!editing || camera.x == null || camera.y == null) return;
    event.stopPropagation();
    event.preventDefault();
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
    onSelect(camera.id);
    setDrag(mode === 'move' ? { id: camera.id, mode, point: { x: camera.x, y: camera.y } } : { id: camera.id, mode, angle: camera.angle ?? 0 });
  };

  const moveDrag = (event: ReactPointerEvent) => {
    if (!drag) return;
    const point = pointFromEvent(event.clientX, event.clientY);
    if (!point) return;
    if (drag.mode === 'move') {
      setDrag({ ...drag, point });
      return;
    }
    const camera = cameras.find((c) => c.id === drag.id);
    if (camera?.x == null || camera.y == null) return;
    setDrag({ ...drag, angle: angleBetween(toPixels({ x: camera.x, y: camera.y }, size), toPixels(point, size)) });
  };

  const endDrag = () => {
    if (!drag) return;
    if (drag.mode === 'move') onMove(drag.id, drag.point);
    else onRotate(drag.id, drag.angle);
    setDrag(null);
  };

  const onDragOver = (event: DragEvent) => {
    if (!editing || !event.dataTransfer.types.includes(DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    setDropActive(true);
  };

  const onDrop = (event: DragEvent) => {
    setDropActive(false);
    const id = event.dataTransfer.getData(DRAG_MIME);
    const point = pointFromEvent(event.clientX, event.clientY);
    if (!editing || !id || !point) return;
    event.preventDefault();
    onDropCamera(id, point);
  };

  const placed = cameras.filter((c) => c.x != null && c.y != null);
  const hoveredCamera = placed.find((c) => c.id === hovered);

  return (
    <div ref={boxRef} className="relative flex h-full w-full items-center justify-center">
      {size.width > 0 && (
        <div
          className={cn('relative select-none', dropActive && 'outline outline-2 outline-offset-2 outline-primary')}
          style={{ width: size.width, height: size.height }}
          onDragOver={onDragOver}
          onDragLeave={() => setDropActive(false)}
          onDrop={onDrop}
        >
          <img src={plan.imageUrl} alt="Qavat rejasi" draggable={false} className="absolute inset-0 h-full w-full rounded-control bg-white object-fill" />
          <svg
            ref={svgRef}
            className={cn('absolute inset-0 h-full w-full', drag && 'cursor-grabbing')}
            viewBox={`0 0 ${size.width} ${size.height}`}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={() => setDrag(null)}
            onClick={() => onSelect(null)}
          >
            {placed.map((camera) => {
              const live = drag?.id === camera.id ? drag : null;
              const point = live?.mode === 'move' ? live.point : { x: camera.x as number, y: camera.y as number };
              const angle = live?.mode === 'rotate' ? live.angle : (camera.angle ?? 0);
              const center = toPixels(point, size);
              const style = STATUS_STYLE[camera.status];
              const selected = camera.id === selectedId;
              const handle = polar(center, angle, radius * HANDLE_GAP);
              return (
                <g key={camera.id}>
                  <path d={conePath(center, angle, camera.fov, radius)} className={cn(style.cone, 'pointer-events-none')} strokeWidth={1} />
                  {(camera.peopleNow ?? 0) > 0 && (
                    // Odamlar zichligi: kamera oldida qancha odam bo'lsa, doira shuncha katta.
                    <circle
                      cx={center.x}
                      cy={center.y}
                      r={DOT_R + 6 + Math.min(24, Math.sqrt(camera.peopleNow ?? 0) * 5)}
                      className="pointer-events-none fill-primary/15 stroke-primary/40"
                      strokeWidth={1}
                    />
                  )}
                  {camera.openEvents > 0 && (
                    <circle cx={center.x} cy={center.y} r={DOT_R + 3} className="pointer-events-none fill-none stroke-danger" strokeWidth={2}>
                      <animate attributeName="r" values={`${DOT_R + 2};${DOT_R + 14}`} dur="1.4s" repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.9;0" dur="1.4s" repeatCount="indefinite" />
                    </circle>
                  )}
                  <circle
                    cx={center.x}
                    cy={center.y}
                    r={selected ? DOT_R + 2 : DOT_R}
                    className={cn(style.dot, editing ? 'cursor-grab' : 'cursor-pointer', camera.openEvents > 0 ? 'stroke-danger' : 'stroke-white')}
                    strokeWidth={2}
                    role="button"
                    aria-label={camera.name}
                    tabIndex={0}
                    onPointerDown={(event) => startDrag(event, camera, 'move')}
                    onPointerEnter={() => setHovered(camera.id)}
                    onPointerLeave={() => setHovered((id) => (id === camera.id ? null : id))}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(camera.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onSelect(camera.id);
                      }
                    }}
                  />
                  {selected && <circle cx={center.x} cy={center.y} r={DOT_R + 6} className="pointer-events-none fill-none stroke-primary" strokeWidth={2} />}
                  {editing && selected && (
                    <>
                      <line x1={center.x} y1={center.y} x2={handle.x} y2={handle.y} className="pointer-events-none stroke-primary" strokeWidth={1.5} strokeDasharray="3 3" />
                      <circle
                        cx={handle.x}
                        cy={handle.y}
                        r={6}
                        className="cursor-crosshair fill-white stroke-primary"
                        strokeWidth={2}
                        aria-label="Yo‘nalishni burish"
                        onPointerDown={(event) => startDrag(event, camera, 'rotate')}
                        onClick={(event) => event.stopPropagation()}
                      />
                    </>
                  )}
                </g>
              );
            })}
          </svg>
          {hoveredCamera && !drag && (
            <span
              className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded bg-fg/90 px-2 py-0.5 text-[12px] font-semibold text-white shadow-pop"
              style={{ left: (hoveredCamera.x as number) * size.width, top: (hoveredCamera.y as number) * size.height - DOT_R - 26 }}
            >
              {hoveredCamera.name}
              {(hoveredCamera.peopleNow ?? 0) > 0 && <span className="ms-1.5 font-normal">· {hoveredCamera.peopleNow} kishi</span>}
              {hoveredCamera.openEvents > 0 && <span className="ms-1.5 text-danger-soft">· {hoveredCamera.openEvents}</span>}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
