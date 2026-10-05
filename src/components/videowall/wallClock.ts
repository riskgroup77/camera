import { useSyncExternalStore } from 'react';

/** Videodevor soati — butun ekran uchun BITTA soniyalik taymer.
 *
 * Har katakda vaqt tamg'asi turadi; agar har katak o'z `setInterval`ini
 * ochsa, 25 katakli setkada 25 ta taymer bo'lardi. Shu yerda bitta
 * taymer bor, obunachilar birga yangilanadi. Taymer faqat obunachi
 * bo'lganda ishlaydi va varaq fonga o'tsa to'xtaydi (kamera devori
 * soatlari fonda protsessor yemasin).
 *
 * Vaqt mintaqasi — Asia/Tashkent: devor qaysi kompyuterda ochilganidan
 * qat'i nazar, ekrandagi vaqt obyekt vaqti bo'lishi kerak. */

const TICK_MS = 1000;
export const WALL_TIME_ZONE = 'Asia/Tashkent';

const listeners = new Set<() => void>();
let timer: number | null = null;
let snapshot = Date.now();

function tick() {
  snapshot = Date.now();
  for (const listener of listeners) listener();
}

function onVisible() {
  if (document.visibilityState === 'visible') tick();
}

function start() {
  if (timer !== null || typeof window === 'undefined') return;
  timer = window.setInterval(() => {
    if (document.visibilityState !== 'hidden') tick();
  }, TICK_MS);
  document.addEventListener('visibilitychange', onVisible);
}

function stop() {
  if (timer === null) return;
  window.clearInterval(timer);
  timer = null;
  document.removeEventListener('visibilitychange', onVisible);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  start();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) stop();
  };
}

function getSnapshot(): number {
  return snapshot;
}

/** Joriy vaqt (ms) — soniyada bir marta yangilanadi. */
export function useWallClock(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: WALL_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

const dateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: WALL_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** `12:04:07` — Toshkent vaqti, soniyalar bilan. */
export function formatWallTime(value: number | Date): string {
  return timeFormat.format(value);
}

/** `01.03.2024` — Toshkent sanasi. */
export function formatWallDate(value: number | Date): string {
  return dateFormat.format(value).replace(/\//g, '.');
}

/** Faqat sinov uchun: taymerni to'xtatadi. */
export function resetWallClock(): void {
  listeners.clear();
  stop();
}
