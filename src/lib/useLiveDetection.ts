import { useCallback, useEffect, useRef, useState } from 'react';
import { api, isAbortError } from './apiClient';
import { useVisibleInterval } from './useVisibleInterval';
import { tryAcquireLiveDetection, releaseLiveDetection } from './liveDetectionGate';
import { noteServerTime } from './serverClock';
import type { LiveDetectionResult } from '../types';

// 1 s: javob endi ai-worker kuzatuvchisi yozib turgan natijadan o'qiladi
// (camera-api/app/services/live_focus.py) — so'rov kadr olmaydi va tahlil
// qilmaydi, ya'ni tez-tez so'rash serverni yuklamaydi. So'rovning o'zi
// kamerani "operator ko'ryapti" deb belgilaydi: kuzatuvchi uni kutishsiz,
// eng yuqori navbat bilan tahlil qiladi. Ilgari (6 s, har so'rov — yangi
// kadr + tahlil) natija 5-12 s kechikardi.
const POLL_INTERVAL_MS = 1000;

/** Polls GET /api/public/cameras/{id}/live-detection while `enabled` — the
 * face-box overlay's data source. No auth needed (it's the same public,
 * no-token endpoint the Monitoring page's camera feed itself uses); the
 * admin CameraConfigDetailModal calls it the same way. Polling only while a
 * camera is actually being watched (`enabled`) still matters: each call keeps
 * that camera in the AI's real-time focus. */
export function useLiveDetection(
  cameraId: string | undefined,
  enabled: boolean,
  /** Video qaysi yo'l bilan kelyapti — server faqat HLS uchun vaqt farqini o'lchaydi. */
  getPlayer?: () => 'webrtc' | 'hls' | null,
) {
  const [result, setResult] = useState<LiveDetectionResult | null>(null);
  const [slotDenied, setSlotDenied] = useState(false);
  const inFlight = useRef(false);
  const hasSlot = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const [polling, setPolling] = useState(false);

  // Ref orqali: har renderda yangi funksiya kelsa ham so'rov tsikli qayta tuzilmaydi.
  const getPlayerRef = useRef(getPlayer);
  getPlayerRef.current = getPlayer;

  const poll = useCallback(async () => {
    if (!cameraId || inFlight.current) return;
    inFlight.current = true;
    const controller = new AbortController();
    abort.current = controller;
    try {
      const sentAt = Date.now();
      const player = getPlayerRef.current?.();
      const query = player ? `?player=${player}` : '';
      const res = await api.get<LiveDetectionResult>(`/api/public/cameras/${cameraId}/live-detection${query}`, undefined, {
        signal: controller.signal,
      });
      noteServerTime(res.serverTime, sentAt, Date.now());
      if (!controller.signal.aborted) setResult(res);
    } catch (err) {
      if (!isAbortError(err)) {
        // bitta so'rov muvaffaqiyatsiz bo'lsa ham keyingi urinishda davom etamiz
      }
    } finally {
      inFlight.current = false;
    }
  }, [cameraId]);

  useEffect(() => {
    if (!cameraId || !enabled) {
      setResult(null);
      setSlotDenied(false);
      setPolling(false);
      if (cameraId && hasSlot.current) {
        releaseLiveDetection(cameraId);
        hasSlot.current = false;
      }
      return;
    }

    const acquired = tryAcquireLiveDetection(cameraId);
    hasSlot.current = acquired;
    setSlotDenied(!acquired);
    setPolling(acquired);
    if (!acquired) {
      setResult(null);
      return;
    }

    poll();
    return () => {
      abort.current?.abort();
      inFlight.current = false;
      setPolling(false);
      if (hasSlot.current) {
        releaseLiveDetection(cameraId);
        hasSlot.current = false;
      }
    };
  }, [cameraId, enabled, poll]);

  // Yorliq fonga o'tsa so'rovlar to'xtaydi: har bir chaqiruv backendda
  // haqiqiy kadr olish + inference, ko'rilmayotgan kamera uchun bu isrof.
  useVisibleInterval(poll, polling ? POLL_INTERVAL_MS : null);

  return { result, slotDenied };
}
