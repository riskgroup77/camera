import { useEffect, useRef, type RefObject } from 'react';
import { TrackTimeline, type TrackBox } from '../lib/liveTracks';
import type { DetectedFaceStatus, LiveDetectionResult } from '../types';

interface FaceDetectionOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  /** Hozir ko'rinayotgan kadrning server soatidagi payti (ms) yoki null. */
  videoClockRef?: RefObject<() => number | null>;
  detection: LiveDetectionResult | null;
  /** Video elementning object-fit rejimi — ramkalar aynan shu matematika
      bo'yicha joylashtiriladi (pictureRect izohiga qarang). */
  fit?: 'cover' | 'contain';
}

/** Ramka ustidagi yozuv. Kichik yuzga yozuv yo'q — u tahlil qilinmagan,
 *  "notanish" deyish yolg'on bo'lardi. */
export function faceLabel(status: DetectedFaceStatus, name: string | null, asleep: boolean): string {
  const base = status === 'tanildi' ? name ?? 'Tanildi' : status === 'notanish' ? 'Notanish' : '';
  return asleep && base ? `${base} — uxlab qolgan` : base;
}

const TONE: Record<DetectedFaceStatus, string> = {
  tanildi: '#34d399',
  notanish: '#f43f5e',
  kichik: 'rgba(255,255,255,0.55)',
};
const ASLEEP = '#f59e0b';

/** Video tasviri konteyner ichida qayerda turadi (piksel).
 *
 * `cover` kattaroq nisbat bo'yicha kattalashtirib ortig'ini kesadi,
 * `contain` kichikrog'i bo'yicha sig'dirib chetida bo'sh joy qoldiradi.
 * Teskarisini ishlatish ramkalarni butunlay tasvirdan tashqariga chiqaradi. */
export function pictureRect(
  containerW: number,
  containerH: number,
  videoW: number,
  videoH: number,
  fit: 'cover' | 'contain',
): { x: number; y: number; w: number; h: number } | null {
  if (!containerW || !containerH || !videoW || !videoH) return null;
  const ratios = [containerW / videoW, containerH / videoH];
  const scale = fit === 'contain' ? Math.min(...ratios) : Math.max(...ratios);
  const w = videoW * scale;
  const h = videoH * scale;
  return { x: (containerW - w) / 2, y: (containerH - h) / 2, w, h };
}

/** Qaysi paytning ramkalari chiziladi. Video soati yo'q yoki natijalardan
 *  juda uzoq (soat farqi) bo'lsa — eng so'nggi natija, avvalgidek. */
export function overlayTime(clock: number | null, newestAt: number | null, offsetMs: number): number | null {
  if (newestAt == null) return null;
  if (clock == null) return newestAt;
  const t = clock - offsetMs;
  return Math.abs(newestAt - t) > 20_000 ? newestAt : t;
}

/** Yuz ramkalari video ustida: har kadrda qayta chiziladi va videoning
 *  AYNAN o'sha paytiga mos keladi (lib/liveTracks.ts). */
export default function FaceDetectionOverlay({ videoRef, videoClockRef, detection, fit = 'cover' }: FaceDetectionOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const timelineRef = useRef(new TrackTimeline());
  const offsetRef = useRef(0);

  useEffect(() => {
    if (!detection) {
      timelineRef.current.clear();
      return;
    }
    offsetRef.current = detection.clockOffsetMs ?? 0;
    timelineRef.current.add([...(detection.history ?? []), detection]);
  }, [detection]);

  const active = detection !== null;

  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const draw = () => {
      frame = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const video = videoRef.current;
      if (!canvas || !video) return;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const rect = pictureRect(width, height, video.videoWidth || 16, video.videoHeight || 9, fit);
      const timeline = timelineRef.current;
      // HLS vaqt belgisi tuzatishi faqat HLS videoga tegishli; WebRTC
      // (srcObject) tasviri real vaqtda — tuzatish kerak emas.
      const offset = video.srcObject ? 0 : offsetRef.current;
      const t = overlayTime(videoClockRef?.current?.() ?? null, timeline.newestAt, offset);
      if (!rect || t == null) return;
      for (const box of timeline.boxesAt(t)) drawBox(ctx, box, rect);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [active, videoRef, videoClockRef, fit]);

  if (!active) return null;
  return <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />;
}

function drawBox(ctx: CanvasRenderingContext2D, box: TrackBox, rect: { x: number; y: number; w: number; h: number }) {
  const [x1, y1, x2, y2] = box.box;
  const left = rect.x + x1 * rect.w;
  const top = rect.y + y1 * rect.h;
  const w = (x2 - x1) * rect.w;
  const h = (y2 - y1) * rect.h;
  const color = box.asleep ? ASLEEP : TONE[box.status];
  ctx.globalAlpha = box.opacity;
  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.setLineDash(box.status === 'kichik' ? [4, 3] : []);
  ctx.beginPath();
  ctx.roundRect(left, top, w, h, 5);
  ctx.stroke();
  ctx.setLineDash([]);
  const label = faceLabel(box.status, box.name, box.asleep);
  if (label) {
    ctx.font = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif';
    const textW = ctx.measureText(label).width;
    const chipH = 18;
    const chipY = top - chipH - 3 < rect.y ? top + h + 3 : top - chipH - 3;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(left, chipY, textW + 10, chipH, 4);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, left + 5, chipY + chipH / 2 + 0.5);
  }
  ctx.globalAlpha = 1;
}
