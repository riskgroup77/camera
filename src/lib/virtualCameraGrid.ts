import { useEffect, useMemo, useRef, useState } from 'react';
import type { CameraFeed } from '../types';

/** Max concurrent HLS players — viewport'dagi kameralardan faqat shunchasi
 * jonli oqim ochadi; qolganlari placeholder ko'rsatadi (P2 virtual grid). */
export const MAX_ACTIVE_STREAMS = 8;

/**
 * IntersectionObserver orqali ko'rinadigan kamera ID'larini kuzatadi va
 * faqat birinchi MAX_ACTIVE_STREAMS tasiga stream ruxsat beradi.
 */
export function useStreamVisibility(_cameraIds: string[]) {
  const [visibleOrder, setVisibleOrder] = useState<string[]>([]);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        setVisibleOrder((prev) => {
          const next = [...prev];
          for (const entry of entries) {
            const id = entry.target.getAttribute('data-camera-id');
            if (!id) continue;
            const idx = next.indexOf(id);
            if (entry.isIntersecting) {
              if (idx >= 0) next.splice(idx, 1);
              next.push(id);
            } else if (idx >= 0) {
              next.splice(idx, 1);
            }
          }
          return next;
        });
      },
      { rootMargin: '120px', threshold: 0.15 },
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

  const activeStreamIds = useMemo(
    () => new Set(visibleOrder.slice(0, MAX_ACTIVE_STREAMS)),
    [visibleOrder],
  );

  return { setRef, activeStreamIds };
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
