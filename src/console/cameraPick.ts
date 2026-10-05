import type { CameraFeed } from '../types';

/**
 * Konsol kamera paneli uchun SOF yordamchilar — holat ham, so'rov ham yo'q.
 *
 * Panel yig'ilgan holatda bor-yo'g'i 4 ta katak ko'rsatadi, shuning uchun
 * "qaysi 4 ta" degan savol muhim: operator ekranga qaraganda avval
 * ROSTDAN tasvir kelayotgan kameralarni ko'rishi kerak, keyin ulanib
 * turganlarini, va faqat oxirida o'liklarini. Tartib nom bo'yicha
 * barqaror — ro'yxat har daqiqada yangilanadi va kataklar sakrab
 * ketmasligi kerak.
 */

const collator = new Intl.Collator('uz', { numeric: true, sensitivity: 'base' });

/** Kamera ROSTDAN tasvir uzatmoqda: ulangan, kadr kelmoqda va havolasi bor.
 * `hasVideo === false` — "erishiladi, lekin tasvirsiz" (types/index.ts). */
export function isStreaming(camera: CameraFeed): boolean {
  return camera.status === 'live' && camera.hasVideo !== false && Boolean(camera.streamUrl);
}

export interface CameraStats {
  /** Tasvir uzatayotganlar. */
  flowing: number;
  /** Ulangan (faol) kameralar. */
  live: number;
  total: number;
}

export function cameraStats(cameras: readonly CameraFeed[]): CameraStats {
  let flowing = 0;
  let live = 0;
  for (const camera of cameras) {
    if (camera.status === 'live') live += 1;
    if (isStreaming(camera)) flowing += 1;
  }
  return { flowing, live, total: cameras.length };
}

/** Kichik son — oldinroq. 0: tasvir kelmoqda, 1: ulangan (havolasi bor),
 * 2: ulangan, lekin tasvirsiz, 3: oflayn. */
export function relevanceRank(camera: CameraFeed): number {
  if (isStreaming(camera)) return 0;
  if (camera.status === 'live' && camera.streamUrl) return 1;
  if (camera.status === 'live') return 2;
  return 3;
}

/** Eng "gapiradigan" kameralar oldinda; teng bo'lsa — nom bo'yicha. */
export function rankCameras(cameras: readonly CameraFeed[]): CameraFeed[] {
  return [...cameras].sort(
    (a, b) => relevanceRank(a) - relevanceRank(b) || collator.compare(a.name, b.name),
  );
}

/** Yig'ilgan paneldagi mozaika — ko'pi bilan `count` ta katak. */
export function pickMosaic(cameras: readonly CameraFeed[], count = 4): CameraFeed[] {
  return rankCameras(cameras).slice(0, Math.max(0, count));
}

export interface CameraFilter {
  q: string;
  building: string;
  /** Qavat raqami satr ko'rinishida; `none` — qavati belgilanmagan. */
  floor: string;
}

export const EMPTY_FILTER: CameraFilter = { q: '', building: '', floor: '' };

export function isFilterOn(filter: CameraFilter): boolean {
  return Boolean(filter.q.trim() || filter.building || filter.floor);
}

/** Nom, zona, bino yoki kafedra bo'yicha qidiruv + bino/qavat kesimi. */
export function filterCameras(cameras: readonly CameraFeed[], filter: CameraFilter): CameraFeed[] {
  const text = filter.q.trim().toLocaleLowerCase('uz');
  return cameras.filter((camera) => {
    if (filter.building && camera.building !== filter.building) return false;
    if (filter.floor) {
      const floor = typeof camera.floor === 'number' ? String(camera.floor) : 'none';
      if (floor !== filter.floor) return false;
    }
    if (!text) return true;
    const haystack = [camera.name, camera.zone, camera.building, camera.department ?? '']
      .join(' ')
      .toLocaleLowerCase('uz');
    return haystack.includes(text);
  });
}

export function buildingOptions(cameras: readonly CameraFeed[]): string[] {
  const names = new Set<string>();
  for (const camera of cameras) if (camera.building) names.add(camera.building);
  return [...names].sort((a, b) => collator.compare(a, b));
}

/** Qavatlar: raqamlar o'sish tartibida, oxirida `none` (agar bo'lsa). */
export function floorOptions(cameras: readonly CameraFeed[]): string[] {
  const numbers = new Set<number>();
  let unknown = false;
  for (const camera of cameras) {
    if (typeof camera.floor === 'number' && Number.isFinite(camera.floor)) numbers.add(camera.floor);
    else unknown = true;
  }
  const list = [...numbers].sort((a, b) => a - b).map(String);
  return unknown && cameras.length > 0 ? [...list, 'none'] : list;
}

export function floorLabel(value: string): string {
  return value === 'none' ? "Qavatsiz" : `${value}-qavat`;
}

/** Devor setkasi: 4 -> 2 ustun, 9 -> 3, 16 -> 4. */
export const WALL_LAYOUTS = [4, 9, 16] as const;
export type WallLayout = (typeof WALL_LAYOUTS)[number];

export function layoutColumns(layout: WallLayout): number {
  return Math.round(Math.sqrt(layout));
}
