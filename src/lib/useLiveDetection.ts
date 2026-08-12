import { useEffect, useRef, useState } from 'react';
import { api } from './apiClient';
import type { LiveDetectionResult } from '../types';

// 6s, not 3s — found from real testing: each call is a genuine ffmpeg
// frame grab + InsightFace inference pass on the backend, and polling
// this aggressively was starving the background attendance/sleep sweep
// loops of CPU time (a 30s sweep loop was observed stretching to minutes
// between completions while this was polling at 3s — see
// app/services/face_recognition.py's _inference_semaphore, the other
// half of this fix). 6s still reads as "live" for a human watching one
// camera.
const POLL_INTERVAL_MS = 6000;

/** Polls GET /api/public/cameras/{id}/live-detection while `enabled` — the
 * face-box overlay's data source. No auth needed (it's the same public,
 * no-token endpoint the Monitoring page's camera feed itself uses); the
 * admin CameraConfigDetailModal calls it the same way. Deliberately not
 * hooked into WebSocket real-time — each call is a genuine fresh frame
 * grab + inference pass on the backend (see app/routers/public.py's
 * get_live_detection() docstring), so polling only while a camera is
 * actually being watched (`enabled`) matters here more than usual. */
export function useLiveDetection(cameraId: string | undefined, enabled: boolean) {
  const [result, setResult] = useState<LiveDetectionResult | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!cameraId || !enabled) {
      setResult(null);
      return;
    }

    let cancelled = false;

    async function poll() {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const res = await api.get<LiveDetectionResult>(`/api/public/cameras/${cameraId}/live-detection`);
        if (!cancelled) setResult(res);
      } catch {
        // bitta so'rov muvaffaqiyatsiz bo'lsa ham keyingi urinishda davom etamiz
      } finally {
        inFlight.current = false;
      }
    }

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [cameraId, enabled]);

  return result;
}
