import { useSyncExternalStore } from 'react';

/** Butun sahifa uchun BITTA soat taymeri.
 *
 *  Ilgari har bir "muddat" yorlig'i o'z `setInterval`ini ochardi: 50 qatorli
 *  hodisalar ro'yxatida 50 ta taymer va 50 ta alohida qayta chizish. Endi
 *  bitta taymer bor, obunachilar esa bir vaqtda yangilanadi. Taymer faqat
 *  obunachi bo'lganda ishlaydi va yorliq (tab) fonga o'tsa to'xtaydi. */

const TICK_MS = 30_000;

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
  if (timer !== null) return;
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

/** Faqat sinov uchun: ichki holatni tozalaydi. */
export function resetSharedClock(): void {
  listeners.clear();
  stop();
}

/** Nechta obunachi bor (sinov uchun). */
export function sharedClockListenerCount(): number {
  return listeners.size;
}

/** Joriy vaqt (ms) — har 30 soniyada yangilanadi. `enabled === false`
 *  bo'lsa komponent obuna bo'lmaydi (taymerga hissa qo'shmaydi). */
export function useSharedNow(enabled = true): number {
  return useSyncExternalStore(
    enabled ? subscribe : () => () => {},
    getSnapshot,
    getSnapshot,
  );
}
