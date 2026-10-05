import { useEffect, useState, type RefObject } from 'react';

interface ZoneOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  /** [x, y] juftliklari, har biri kadr kengligi/balandligiga nisbatan 0-1
   * oralig'ida normallashtirilgan — app/models/camera.py's
   * restricted_zone_polygon bilan bir xil format. */
  points: [number, number][];
  editable: boolean;
  onAddPoint?: (point: [number, number]) => void;
}

/** Video `object-cover` bilan render qilinganda (konteynerni to'ldiradi,
 * ortiqchasini kesib tashlaydi), bosilgan konteyner pikseli haqiqiy kadr
 * koordinatasiga aylantirilishi kerak — xuddi FaceDetectionOverlay'ning
 * computeBoxes() qilgan teskari amali: konteyner o'lchami emas, videoning
 * o'zi (video.videoWidth/Height) — chunki normallashtirish shu asosda
 * saqlanadi va keyin backendga yuboriladi. */
function toNormalizedPoint(video: HTMLVideoElement, clientX: number, clientY: number): [number, number] | null {
  const rect = video.getBoundingClientRect();
  const frameW = video.videoWidth;
  const frameH = video.videoHeight;
  if (!frameW || !frameH || !rect.width || !rect.height) return null;

  const scale = Math.max(rect.width / frameW, rect.height / frameH);
  const offsetX = (rect.width - frameW * scale) / 2;
  const offsetY = (rect.height - frameH * scale) / 2;

  const containerX = clientX - rect.left;
  const containerY = clientY - rect.top;
  const x = (containerX - offsetX) / scale / frameW;
  const y = (containerY - offsetY) / scale / frameH;
  return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
}

export default function ZoneOverlay({ videoRef, points, editable, onAddPoint }: ZoneOverlayProps) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const rerender = () => setTick((t) => t + 1);
    rerender();
    const observer = new ResizeObserver(rerender);
    observer.observe(video);
    return () => observer.disconnect();
  }, [videoRef]);

  const video = videoRef.current;
  if (!video) return null;

  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!editable || !onAddPoint || !video) return;
    const point = toNormalizedPoint(video, e.clientX, e.clientY);
    if (point) onAddPoint(point);
  }

  const svgPoints = points.map(([x, y]) => `${x * 100},${y * 100}`).join(' ');

  return (
    <div
      className={`absolute inset-0 overflow-hidden ${editable ? 'cursor-crosshair' : 'pointer-events-none'}`}
      onClick={handleClick}
    >
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {points.length >= 2 && (
          <polygon
            points={svgPoints}
            fill="rgba(239,68,68,0.25)"
            stroke="rgb(239,68,68)"
            strokeWidth={0.4}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {points.map(([x, y], i) => (
          <circle key={i} cx={x * 100} cy={y * 100} r={1.2} fill="rgb(239,68,68)" stroke="white" strokeWidth={0.3} />
        ))}
      </svg>
    </div>
  );
}
