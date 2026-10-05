import { ApiError, api, buildQuery } from './apiClient';
import { sanitizeView, type WallView } from './videoWall';

/* ── Turlar (camera-api/app/schemas/wall_view.py bilan mos) ── */

export type WallViewKind = 'view' | 'tour';

export interface ServerWallView {
  id: string;
  name: string;
  kind: WallViewKind;
  payload: Record<string, unknown>;
  shared: boolean;
  ownerId: string;
  ownerName: string | null;
  mine: boolean;
  canEdit: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface WallViewImportResult {
  created: number;
  updated: number;
  skipped: number;
  items: ServerWallView[];
}

/** Ko'rinish haqida serverdan kelgan qo'shimcha — kimniki, tahrirlash
 * mumkinmi. Faqat shu brauzerda yaratilgan (hali serverga chiqmagan)
 * ko'rinishda bo'lmaydi: u o'ziniki deb hisoblanadi. */
export interface ViewMeta {
  mine: boolean;
  canEdit: boolean;
  shared: boolean;
  ownerName: string | null;
}

export type ViewMetaMap = Record<string, ViewMeta>;

const BASE = '/api/devor-korinishlar';

export const wallViewsApi = {
  list: (kind: WallViewKind = 'view') => api.get<ServerWallView[]>(`${BASE}${buildQuery({ kind })}`),
  create: (view: WallView) =>
    api.post<ServerWallView>(BASE, { id: view.id, name: view.name, kind: 'view', payload: viewPayload(view) }),
  update: (view: WallView) => api.patch<ServerWallView>(`${BASE}/${view.id}`, { name: view.name, payload: viewPayload(view) }),
  remove: (id: string) => api.del(`${BASE}/${id}`),
  importViews: (views: readonly WallView[]) =>
    api.post<WallViewImportResult>(`${BASE}/import`, {
      items: views.map((view) => ({
        id: view.id,
        name: view.name,
        kind: 'view',
        payload: viewPayload(view),
        updatedAt: view.updatedAt,
      })),
    }),
};

/* ── Sof yordamchilar (wallViewsApi.test.ts) ── */

/** Serverda saqlanadigan qism — frontend localStorage'da nima saqlasa shu. */
export function viewPayload(view: WallView): { layout: WallView['layout']; tiles: WallView['tiles'] } {
  return { layout: view.layout, tiles: view.tiles };
}

/** Server javobini devor ko'rinishiga aylantiradi; buzilgan payload — null
 * (boshqa versiyadagi frontend yozgan bo'lsa ham devor sinmasin). */
export function fromServer(item: ServerWallView): { view: WallView; meta: ViewMeta } | null {
  const payload = (item.payload && typeof item.payload === 'object' ? item.payload : {}) as Record<string, unknown>;
  const view = sanitizeView({
    id: item.id,
    name: item.name,
    layout: payload.layout,
    tiles: payload.tiles,
    updatedAt: item.updatedAt ?? undefined,
  });
  if (!view) return null;
  return { view, meta: { mine: item.mine, canEdit: item.canEdit, shared: item.shared, ownerName: item.ownerName } };
}

export function fromServerList(items: readonly ServerWallView[]): { views: WallView[]; meta: ViewMetaMap } {
  const views: WallView[] = [];
  const meta: ViewMetaMap = {};
  for (const item of items) {
    const parsed = fromServer(item);
    if (!parsed || meta[parsed.view.id]) continue;
    views.push(parsed.view);
    meta[parsed.view.id] = parsed.meta;
  }
  return { views, meta };
}

export interface ViewsDiff {
  created: WallView[];
  updated: { before: WallView; after: WallView }[];
  removed: { view: WallView; index: number }[];
}

function sameContent(a: WallView, b: WallView): boolean {
  return a.name === b.name && a.layout === b.layout && a.tiles.length === b.tiles.length && a.tiles.every((id, i) => id === b.tiles[i]);
}

/** Ikki ro'yxat farqi (id bo'yicha) — optimistik o'zgarishni serverga
 * qaysi so'rovlar bilan yuborishni aniqlaydi. */
export function diffViews(prev: readonly WallView[], next: readonly WallView[]): ViewsDiff {
  const before = new Map(prev.map((view) => [view.id, view]));
  const after = new Set(next.map((view) => view.id));
  const diff: ViewsDiff = { created: [], updated: [], removed: [] };
  for (const view of next) {
    const old = before.get(view.id);
    if (!old) diff.created.push(view);
    else if (!sameContent(old, view)) diff.updated.push({ before: old, after: view });
  }
  prev.forEach((view, index) => {
    if (!after.has(view.id)) diff.removed.push({ view, index });
  });
  return diff;
}

/** Tarmoq/server nosozligi (qayta urinsa bo'ladi) yoki aniq rad javobi
 * (403/404/422 — optimistik o'zgarish bekor qilinadi). */
export function isOfflineError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status === 0 || error.status >= 500;
}

/** Bir martalik importga (va oflayn yozuvlarni qayta yuborishga) faqat
 * o'zimizniki ketadi: boshqaning umumiy ko'rinishi keshda bor, lekin uni
 * "o'zimniki" qilib serverga yozib bo'lmaydi. */
export function ownLocalViews(views: readonly WallView[], meta: ViewMetaMap): WallView[] {
  return views.filter((view) => meta[view.id]?.mine !== false);
}

/** Ko'rinish ro'yxatidagi "umumiy" belgisi: boshqa operator ulashgan. */
export function isForeignShared(meta: ViewMeta | undefined): boolean {
  return Boolean(meta && !meta.mine);
}
