import { useEffect, useRef, useState } from 'react';
import { api } from './apiClient';
import type { CameraAnalysisStatus } from '../types';

const POLL_INTERVAL_MS = 5000;

/** Polls GET /api/public/cameras/{id}/analysis-status for background sweep badge. */
export function useCameraAnalysisStatus(cameraId: string | undefined, enabled: boolean) {
  const [status, setStatus] = useState<CameraAnalysisStatus | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!cameraId || !enabled) {
      setStatus(null);
      return;
    }

    let cancelled = false;

    async function poll() {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const res = await api.get<CameraAnalysisStatus>(`/api/public/cameras/${cameraId}/analysis-status`);
        if (!cancelled) setStatus(res);
      } catch {
        /* ignore transient errors */
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

  return status;
}
