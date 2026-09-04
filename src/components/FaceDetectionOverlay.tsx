import { useEffect, useState, type RefObject } from 'react';
import type { LiveDetectionResult } from '../types';

interface FaceDetectionOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  detection: LiveDetectionResult | null;
  /** Video elementning object-fit rejimi. Ramkalar aynan shu matematika
      bo'yicha joylashtiriladi — computeBoxes izohiga qarang. */
  fit?: 'cover' | 'contain';
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

/** Draws a box + label over each detected face on top of a <video>.
 *
 * A face's [x1,y1,x2,y2] is in the SOURCE frame's pixel coordinates, so
 * it has to go through exactly the same fit-and-scale math the browser
 * applied to the video itself — a plain width-ratio scale makes the
 * boxes drift off the faces the moment the video's aspect ratio differs
 * from its container's.
 *
 * Which math depends on object-fit, and getting it backwards is worse
 * than useless: `cover` scales to the LARGER ratio and crops the
 * overflow, `contain` scales to the SMALLER one and letterboxes. Using
 * cover's math on a contained video puts every box outside the picture. */
function computeBoxes(
  video: HTMLVideoElement,
  detection: LiveDetectionResult,
  fit: 'cover' | 'contain',
): BoxStyle[] {
  const containerW = video.clientWidth;
  const containerH = video.clientHeight;
  const { frameWidth, frameHeight, faces } = detection;
  if (!containerW || !containerH || !frameWidth || !frameHeight) return [];

  const ratios = [containerW / frameWidth, containerH / frameHeight];
  const scale = fit === 'contain' ? Math.min(...ratios) : Math.max(...ratios);
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

export default function FaceDetectionOverlay({ videoRef, detection, fit = 'cover' }: FaceDetectionOverlayProps) {
  const [boxes, setBoxes] = useState<BoxStyle[]>([]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !detection) {
      setBoxes([]);
      return;
    }

    function recompute() {
      if (video && detection) setBoxes(computeBoxes(video, detection, fit));
    }

    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(video);
    return () => observer.disconnect();
  }, [videoRef, detection, fit]);

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
