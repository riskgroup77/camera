import { useEffect, useRef, useState } from 'react';
import type { CameraFeed } from '../types';

/**
 * IntersectionObserver orqali viewport'dagi kamera ID'larini kuzatadi.
 * Navbat cheklovi yo'q — ekranda ko'rinadigan barcha kameralar oqim ochadi.
 */
export function useStreamVisibility(_cameraIds: string[]) {
  const [visibleIds, setVisibleIds] = useState<Set<string>>(() => new Set());
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        setVisibleIds((prev) => {
          const next = new Set(prev);
          for (const entry of entries) {
            const id = entry.target.getAttribute('data-camera-id');
            if (!id) continue;
            if (entry.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        });
      },
      { rootMargin: '80px', threshold: 0.08 },
    );
    return () => observerRef.current?.disconnect();
  }, []);

  const setRef = (cameraId: string) => (el: HTMLElement | null) => {
    const obs = observerRef.current;
    if (!obs) return;
    const existing = document.querySelector(`[data-camera-id="${cameraId}"]`);
    if (existing && existing !== el) {
      obs.unobserve(existing);
    }
    if (el) obs.observe(el);
    else {
      const node = document.querySelector(`[data-camera-id="${cameraId}"]`);
      if (node) obs.unobserve(node);
    }
  };

  return { setRef, visibleIds };
}

export type GridLayoutMode = 'scroll' | 'wall-4' | 'wall-9' | 'wall-16';

export function wallLimit(mode: GridLayoutMode): number | null {
  switch (mode) {
    case 'wall-4':
      return 4;
    case 'wall-9':
      return 9;
    case 'wall-16':
      return 16;
    default:
      return null;
  }
}

export function gridColsClass(mode: GridLayoutMode): string {
  switch (mode) {
    case 'wall-4':
      return 'grid-cols-2';
    case 'wall-9':
      return 'grid-cols-3';
    case 'wall-16':
      return 'grid-cols-4';
    default:
      return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5';
  }
}

export function camerasForLayout(cameras: CameraFeed[], mode: GridLayoutMode): CameraFeed[] {
  const limit = wallLimit(mode);
  return limit ? cameras.slice(0, limit) : cameras;
}

/** Devor rejimida yoki scroll'da ko'rinadigan kamera uchun oqim yoqilsinmi. */
export function shouldPlayStream(
  camera: CameraFeed,
  wall: number | null,
  visibleIds: Set<string>,
): boolean {
  if (camera.status !== 'live') return false;
  if (wall !== null) return true;
  return visibleIds.has(camera.id);
}
