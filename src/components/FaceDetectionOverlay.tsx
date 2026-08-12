import { useEffect, useState, type RefObject } from 'react';
import type { LiveDetectionResult } from '../types';

interface FaceDetectionOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  detection: LiveDetectionResult | null;
}

interface BoxStyle {
  key: string;
  left: number;
  top: number;
  width: number;
  height: number;
  label: string;
  asleep: boolean;
  identified: boolean;
}

/** Draws a box + label over each detected face on top of a <video> that's
 * rendered with `object-cover` (fills its box, crops the overflow instead
 * of letterboxing) — so a face's [x1,y1,x2,y2] in the source frame's pixel
 * coordinates has to go through the same crop-and-scale math the browser
 * applies to the video itself, not a plain width-ratio scale, or the boxes
 * drift off the actual face as soon as the video's aspect ratio doesn't
 * match its container's. */
function computeBoxes(video: HTMLVideoElement, detection: LiveDetectionResult): BoxStyle[] {
  const containerW = video.clientWidth;
  const containerH = video.clientHeight;
  const { frameWidth, frameHeight, faces } = detection;
  if (!containerW || !containerH || !frameWidth || !frameHeight) return [];

  const scale = Math.max(containerW / frameWidth, containerH / frameHeight);
  const offsetX = (containerW - frameWidth * scale) / 2;
  const offsetY = (containerH - frameHeight * scale) / 2;

  return faces.map((face, i) => {
    const [x1, y1, x2, y2] = face.bbox;
    return {
      key: `${i}-${x1}-${y1}`,
      left: offsetX + x1 * scale,
      top: offsetY + y1 * scale,
      width: (x2 - x1) * scale,
      height: (y2 - y1) * scale,
      label: face.asleep ? `${face.personName ?? "Noma'lum"} — uxlab qolgan` : face.personName ?? "Noma'lum",
      asleep: face.asleep,
      identified: !!face.personName,
    };
  });
}

export default function FaceDetectionOverlay({ videoRef, detection }: FaceDetectionOverlayProps) {
  const [boxes, setBoxes] = useState<BoxStyle[]>([]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !detection) {
      setBoxes([]);
      return;
    }

    function recompute() {
      if (video) setBoxes(computeBoxes(video, detection));
    }

    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(video);
    return () => observer.disconnect();
  }, [videoRef, detection]);

  if (boxes.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {boxes.map((box) => (
        <div
          key={box.key}
          className={`absolute rounded-md border-2 ${box.asleep ? 'border-amber-400' : box.identified ? 'border-emerald-400' : 'border-slate-300'}`}
          style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
        >
          <span
            className={`absolute -top-6 left-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${
              box.asleep ? 'bg-amber-500' : box.identified ? 'bg-emerald-500' : 'bg-slate-500'
            }`}
          >
            {box.label}
          </span>
        </div>
      ))}
    </div>
  );
}
