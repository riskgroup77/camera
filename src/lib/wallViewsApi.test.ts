import { describe, expect, it } from 'vitest';
import { ApiError } from './apiClient';
import type { WallView } from './videoWall';
import {
  diffViews,
  fromServer,
  fromServerList,
  isForeignShared,
  isOfflineError,
  ownLocalViews,
  viewPayload,
  type ServerWallView,
} from './wallViewsApi';

const view = (id: string, name = id, tiles: (string | null)[] = ['cam-1', null, null, null]): WallView => ({
  id,
  name,
  layout: '2x2',
  tiles,
  updatedAt: '2026-09-24T10:00:00.000Z',
});

const server = (over: Partial<ServerWallView> = {}): ServerWallView => ({
  id: 'a',
  name: 'Kirishlar',
  kind: 'view',
  payload: { layout: '2x2', tiles: ['cam-1', null, null, null] },
  shared: true,
  ownerId: 'u-1',
  ownerName: 'Behzod Karimov',
  mine: false,
  canEdit: false,
  createdAt: '2026-09-24T10:00:00+05:00',
  updatedAt: '2026-09-24T10:00:00+05:00',
  ...over,
});

describe('wallViewsApi helpers', () => {
  it('payload — faqat setka va kataklar', () => {
    expect(viewPayload(view('a'))).toEqual({ layout: '2x2', tiles: ['cam-1', null, null, null] });
  });

  it("server javobini ko'rinishga aylantiradi, buzilganini tashlaydi", () => {
    const parsed = fromServer(server());
    expect(parsed?.view).toMatchObject({ id: 'a', name: 'Kirishlar', layout: '2x2', updatedAt: '2026-09-24T10:00:00+05:00' });
    expect(parsed?.meta).toEqual({ mine: false, canEdit: false, shared: true, ownerName: 'Behzod Karimov' });
    expect(fromServer(server({ payload: { layout: '9x9', tiles: [] } }))).toBeNull();

    const list = fromServerList([server(), server({ id: 'b', payload: {} }), server({ name: 'Takror' }), server({ id: 'c', mine: true })]);
    expect(list.views.map((v) => v.id)).toEqual(['a', 'c']);
    expect(list.meta.c.mine).toBe(true);
  });

  it("farq: yaratilgan, o'zgargan, o'chirilgan", () => {
    const prev = [view('a'), view('b'), view('c')];
    const next = [view('a'), view('b', 'Yangi nom'), view('d')];
    const diff = diffViews(prev, next);
    expect(diff.created.map((v) => v.id)).toEqual(['d']);
    expect(diff.updated.map((u) => [u.before.name, u.after.name])).toEqual([['b', 'Yangi nom']]);
    expect(diff.removed).toEqual([{ view: prev[2], index: 2 }]);
    // Faqat vaqt belgisi o'zgarsa — so'rov yo'q.
    expect(diffViews(prev, prev.map((v) => ({ ...v, updatedAt: 'x' }))).updated).toEqual([]);
    expect(diffViews(prev, [view('a', 'a', ['cam-2', null, null, null]), view('b'), view('c')]).updated).toHaveLength(1);
  });

  it('oflayn xato va aniq rad javobini ajratadi', () => {
    expect(isOfflineError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isOfflineError(new ApiError(0, 'vaqt tugadi'))).toBe(true);
    expect(isOfflineError(new ApiError(502, 'gateway'))).toBe(true);
    expect(isOfflineError(new ApiError(403, "huquq yo'q"))).toBe(false);
    expect(isOfflineError(new ApiError(404, 'topilmadi'))).toBe(false);
  });

  it("importga faqat o'zimizniki; umumiy belgisi faqat begonada", () => {
    const meta = { a: { mine: false, canEdit: false, shared: true, ownerName: 'X' }, b: { mine: true, canEdit: true, shared: true, ownerName: null } };
    expect(ownLocalViews([view('a'), view('b'), view('c')], meta).map((v) => v.id)).toEqual(['b', 'c']);
    expect(isForeignShared(meta.a)).toBe(true);
    expect(isForeignShared(meta.b)).toBe(false);
    expect(isForeignShared(undefined)).toBe(false);
  });
});
