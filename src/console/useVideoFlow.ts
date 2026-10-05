import { useEffect, useRef, useState } from 'react';

/**
 * "Bu katakda tasvir ROSTDAN kelyaptimi?"
 *
 * Kameraning `status: 'live'` bo'lishi — backend bir necha daqiqa oldin
 * unga yetib borganini bildiradi, brauzerda hozir kadr almashayotganini
 * emas. Jonli nuqta (`.live-dot`) esa aynan ikkinchisini va'da qiladi,
 * shuning uchun u <video> elementining O'ZIDAN o'lchanadi:
 * `currentTime` siljiyaptimi.
 *
 * Pleyerning ichiga tegilmaydi (LiveVideoPlayer.tsx qattiqlashtirilgan va
 * o'zgartirilmaydi) — katak konteyneridagi <video> tashqaridan kuzatiladi.
 * O'lchov faqat varaq ko'rinib turganda ishlaydi: fonda brauzerning o'zi
 * videoni sekinlashtiradi, ya'ni har qanday o'lchov yolg'on bo'lardi.
 */

export type FlowState = 'starting' | 'flowing' | 'stalled';

export interface FlowSample {
  /** Oxirgi o'lchovdan beri kadr vaqti siljidimi. */
  progressed: boolean;
  /** Oxirgi siljishdan beri o'tgan vaqt. */
  sinceProgressMs: number;
  /** Kuzatuv boshlanganidan beri o'tgan vaqt. */
  sinceStartMs: number;
}

export interface FlowLimits {
  /** Birinchi kadrni shuncha kutamiz (HLS + navbat + transkod). */
  startGraceMs: number;
  /** Oqim shuncha turib qolsa — uzilgan deb ko'rsatiladi. */
  stallAfterMs: number;
}

export const FLOW_LIMITS: FlowLimits = { startGraceMs: 14_000, stallAfterMs: 5_000 };

/** Sof qaror — holatga ham, DOM'ga ham bog'liq emas (test qilinadi). */
export function nextFlowState(
  prev: FlowState,
  sample: FlowSample,
  limits: FlowLimits = FLOW_LIMITS,
): FlowState {
  if (sample.progressed) return 'flowing';
  if (prev === 'flowing') return sample.sinceProgressMs > limits.stallAfterMs ? 'stalled' : 'flowing';
  if (prev === 'stalled') return 'stalled';
  return sample.sinceStartMs > limits.startGraceMs ? 'stalled' : 'starting';
}

const SAMPLE_MS = 1_200;

/** Konteyner ichidagi <video> uchun oqim holati. `enabled` false bo'lsa
 * (pleyer umuman ochilmagan yoki varaq fonda) — taymer ishlamaydi. */
export function useVideoFlow(
  container: { current: HTMLElement | null },
  enabled: boolean,
  limits: FlowLimits = FLOW_LIMITS,
): FlowState {
  const [state, setState] = useState<FlowState>('starting');
  const stateRef = useRef<FlowState>('starting');
  stateRef.current = state;

  useEffect(() => {
    if (!enabled) {
      setState('starting');
      return;
    }
    let timer: number | undefined;
    const startedAt = Date.now();
    let lastTime = -1;
    let lastProgressAt = startedAt;

    const sample = () => {
      const video = container.current?.querySelector('video') ?? null;
      const now = Date.now();
      const alive =
        !!video && video.readyState >= 2 && video.videoWidth > 0 && !video.paused && video.currentTime !== lastTime;
      if (alive) {
        lastTime = video!.currentTime;
        lastProgressAt = now;
      }
      const next = nextFlowState(
        stateRef.current,
        { progressed: alive, sinceProgressMs: now - lastProgressAt, sinceStartMs: now - startedAt },
        limits,
      );
      if (next !== stateRef.current) {
        stateRef.current = next;
        setState(next);
      }
    };

    const start = () => {
      if (timer !== undefined) return;
      lastProgressAt = Date.now();
      timer = window.setInterval(sample, SAMPLE_MS);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    // Ko'rinmayotgan varaqda taymer yurmaydi (konsol qoidasi).
    const onVisibility = () => (document.hidden ? stop() : start());

    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [container, enabled, limits]);

  return state;
}
