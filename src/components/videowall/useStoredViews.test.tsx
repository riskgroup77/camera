import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { ApiError } from '../../lib/apiClient';
import type { WallView } from '../../lib/videoWall';
import type { ServerWallView } from '../../lib/wallViewsApi';
import {
  VIEWS_IMPORTED_PREFIX,
  VIEWS_PENDING_KEY,
  VIEWS_STORAGE_KEY,
  useStoredViews,
} from './useStoredViews';

vi.mock('../../lib/config', () => ({
  config: { apiBaseUrl: 'https://api.test', realtimeUrl: '', streamGatewayUrl: '' },
  isBackendConfigured: true,
}));
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ role: 'admin', userName: 'operator', token: 't' }) }));

const apiMock = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  importViews: vi.fn(),
}));
vi.mock('../../lib/wallViewsApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/wallViewsApi')>();
  return { ...original, wallViewsApi: apiMock };
});

const local = (id: string, name = id): WallView => ({
  id,
  name,
  layout: '2x2',
  tiles: ['cam-1', null, null, null],
  updatedAt: '2026-09-20T10:00:00.000Z',
});

const server = (id: string, over: Partial<ServerWallView> = {}): ServerWallView => ({
  id,
  name: id,
  kind: 'view',
  payload: { layout: '2x2', tiles: ['cam-1', null, null, null] },
  shared: true,
  ownerId: 'u-1',
  ownerName: 'Behzod Karimov',
  mine: true,
  canEdit: true,
  createdAt: null,
  updatedAt: '2026-09-24T10:00:00+05:00',
  ...over,
});

beforeEach(() => {
  localStorage.clear();
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  apiMock.list.mockResolvedValue([]);
});

afterEach(() => localStorage.clear());

describe('useStoredViews (server)', () => {
  it("brauzerdagi ko'rinishlarni bir marta serverga ko'chiradi, keyin faqat ro'yxat", async () => {
    localStorage.setItem(VIEWS_STORAGE_KEY, JSON.stringify([local('a'), local('b')]));
    apiMock.importViews.mockResolvedValue({
      created: 2,
      updated: 0,
      skipped: 0,
      items: [server('a'), server('b'), server('x', { name: 'Begona', mine: false, canEdit: false })],
    });

    const { result, unmount } = renderHook(() => useStoredViews());
    await waitFor(() => expect(result.current[0]).toHaveLength(3));
    expect(apiMock.importViews).toHaveBeenCalledTimes(1);
    expect(apiMock.importViews.mock.calls[0][0].map((v: WallView) => v.id)).toEqual(['a', 'b']);
    expect(result.current[2].remote).toBe(true);
    expect(result.current[2].meta.x).toMatchObject({ mine: false, ownerName: 'Behzod Karimov' });
    expect(localStorage.getItem(`${VIEWS_IMPORTED_PREFIX}operator`)).toBe('1');
    // Kesh ham yangilangan — oflayn bo'lsa shu ishlatiladi.
    expect(JSON.parse(localStorage.getItem(VIEWS_STORAGE_KEY) ?? '[]')).toHaveLength(3);
    unmount();

    apiMock.list.mockResolvedValue([server('a')]);
    const second = renderHook(() => useStoredViews());
    await waitFor(() => expect(second.result.current[0].map((v) => v.id)).toEqual(['a']));
    expect(apiMock.importViews).toHaveBeenCalledTimes(1);
    expect(apiMock.list).toHaveBeenCalledTimes(1);
  });

  it("yangi ko'rinish darhol chiqadi, server id'ni almashtirsa belgi ko'chadi", async () => {
    localStorage.setItem(`${VIEWS_IMPORTED_PREFIX}operator`, '1');
    const onIdChange = vi.fn();
    apiMock.create.mockResolvedValue(server('11111111-1111-4111-8111-111111111111', { name: 'Yangi' }));
    const { result } = renderHook(() => useStoredViews({ onIdChange }));
    await waitFor(() => expect(apiMock.list).toHaveBeenCalled());

    act(() => result.current[1]((prev) => [...prev, local('v-eski', 'Yangi')]));
    expect(result.current[0].map((v) => v.name)).toEqual(['Yangi']);
    await waitFor(() => expect(result.current[0][0].id).toBe('11111111-1111-4111-8111-111111111111'));
    expect(onIdChange).toHaveBeenCalledWith('v-eski', '11111111-1111-4111-8111-111111111111');
  });

  it("server rad etsa o'zgarish qaytariladi", async () => {
    localStorage.setItem(`${VIEWS_IMPORTED_PREFIX}operator`, '1');
    apiMock.list.mockResolvedValue([server('x', { name: 'Begona', mine: false, canEdit: false })]);
    apiMock.update.mockRejectedValue(new ApiError(403, "Faqat egasi o'zgartira oladi"));
    const onError = vi.fn();
    const { result } = renderHook(() => useStoredViews({ onError }));
    await waitFor(() => expect(result.current[0]).toHaveLength(1));

    act(() => result.current[1]((prev) => prev.map((v) => ({ ...v, name: 'Buzilgan' }))));
    expect(result.current[0][0].name).toBe('Buzilgan');
    await waitFor(() => expect(result.current[0][0].name).toBe('Begona'));
    expect(onError).toHaveBeenCalledWith("Faqat egasi o'zgartira oladi");
  });

  it("oflayn o'chirish keyingi yuklashda serverga yetkaziladi", async () => {
    localStorage.setItem(`${VIEWS_IMPORTED_PREFIX}operator`, '1');
    apiMock.list.mockResolvedValue([server('a')]);
    apiMock.remove.mockRejectedValue(new TypeError('Failed to fetch'));
    const { result, unmount } = renderHook(() => useStoredViews());
    await waitFor(() => expect(result.current[0]).toHaveLength(1));

    act(() => result.current[1]([]));
    expect(result.current[0]).toEqual([]);
    await waitFor(() => expect(JSON.parse(localStorage.getItem(VIEWS_PENDING_KEY) ?? '{}').deleted).toEqual(['a']));
    unmount();

    apiMock.remove.mockReset();
    apiMock.remove.mockResolvedValue(undefined);
    apiMock.list.mockResolvedValue([]);
    const again = renderHook(() => useStoredViews());
    await waitFor(() => expect(apiMock.remove).toHaveBeenCalledWith('a'));
    await waitFor(() => expect(localStorage.getItem(VIEWS_PENDING_KEY)).toBeNull());
    expect(again.result.current[0]).toEqual([]);
  });

  it('server yetib bo‘lmasa kesh bilan ishlaydi', async () => {
    localStorage.setItem(VIEWS_STORAGE_KEY, JSON.stringify([local('a')]));
    apiMock.importViews.mockRejectedValue(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useStoredViews());
    await waitFor(() => expect(apiMock.importViews).toHaveBeenCalled());
    expect(result.current[0].map((v) => v.id)).toEqual(['a']);
    expect(localStorage.getItem(`${VIEWS_IMPORTED_PREFIX}operator`)).toBeNull();
  });
});
