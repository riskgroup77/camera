import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { isBackendConfigured } from '../../lib/config';
import { sanitizeViews, type WallView } from '../../lib/videoWall';
import {
  diffViews,
  fromServer,
  fromServerList,
  isOfflineError,
  ownLocalViews,
  wallViewsApi,
  type ServerWallView,
  type ViewMeta,
  type ViewMetaMap,
} from '../../lib/wallViewsApi';

/** Saqlangan ko'rinishlar — serverda (/api/devor-korinishlar), boshqa ish
 * joylaridagi operatorlar bilan umumiy.
 *
 * - Har o'zgarish OPTIMISTIK: ro'yxat darhol yangilanadi, so'rov orqada
 *   ketadi; server aniq rad etsa (403/404/422) o'zgarish qaytariladi.
 * - localStorage — kesh va oflayn zaxira: server yo'q (demo) yoki tarmoq
 *   uzilgan bo'lsa devor avvalgidek shu brauzer bilan ishlaydi; tarmoq
 *   qaytganda o'zimizning ko'rinishlar import orqali qayta yuboriladi.
 * - Bir martalik import: server paydo bo'lishidan oldin shu brauzerda
 *   saqlangan ko'rinishlar birinchi yuklashda serverga ko'chiriladi va
 *   foydalanuvchi bo'yicha "ko'chirildi" deb belgilanadi.
 * - Boshqa oynadagi o'zgarish (`storage` hodisasi) shu yerga ham keladi —
 *   ikkinchi monitordagi /videodevor oynasi yangilangan ko'rinishni oladi. */
export const VIEWS_STORAGE_KEY = 'videowall-views';
export const VIEWS_META_KEY = 'videowall-views-meta';
/** + foydalanuvchi nomi: bitta brauzerda ikki operator navbatma-navbat
 * ishlasa, ikkinchisining ko'rinishlari ham o'z nomiga ko'chsin. */
export const VIEWS_IMPORTED_PREFIX = 'videowall-views-imported:';
/** Oflayn paytda qilingan o'zgarishlar: serverga hali yetmagan. */
export const VIEWS_PENDING_KEY = 'videowall-views-pending';

/** Fokusga qaytganda boshqalarning yangi ko'rinishlarini olish — lekin
 * har oyna almashishida emas. */
const REFRESH_GAP_MS = 30_000;

interface Pending {
  dirty: boolean;
  deleted: string[];
}

function readJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* xotira to'la yoki taqiqlangan — holat baribir shu oynada yangilanadi */
  }
}

function readViews(): WallView[] {
  return sanitizeViews(readJson(VIEWS_STORAGE_KEY));
}

function readMeta(): ViewMetaMap {
  const raw = readJson(VIEWS_META_KEY);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const meta: ViewMetaMap = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== 'object') continue;
    const item = value as Record<string, unknown>;
    meta[id] = {
      mine: item.mine !== false,
      canEdit: item.canEdit !== false,
      shared: item.shared !== false,
      ownerName: typeof item.ownerName === 'string' ? item.ownerName : null,
    };
  }
  return meta;
}

function readPending(): Pending {
  const raw = readJson(VIEWS_PENDING_KEY) as Partial<Pending> | null;
  return {
    dirty: Boolean(raw?.dirty),
    deleted: Array.isArray(raw?.deleted) ? raw!.deleted.filter((id): id is string => typeof id === 'string') : [],
  };
}

function importedFlag(userName: string | null): string {
  return `${VIEWS_IMPORTED_PREFIX}${userName ?? ''}`;
}

export interface StoredViewsOptions {
  /** Server rad etgan o'zgarish (qaytarildi) — foydalanuvchiga xabar. */
  onError?: (message: string) => void;
  /** Server id'ni almashtirdi (band yoki eski "v-..." id) — faol ko'rinish
   * belgisi yo'qolmasin. */
  onIdChange?: (from: string, to: string) => void;
}

export interface StoredViewsInfo {
  meta: ViewMetaMap;
  /** Ko'rinishlar serverda (umumiy) — aks holda faqat shu brauzerda. */
  remote: boolean;
}

type ViewsUpdate = WallView[] | ((prev: WallView[]) => WallView[]);

export function useStoredViews(options: StoredViewsOptions = {}) {
  const { token, userName } = useAuth();
  const remote = isBackendConfigured && Boolean(token);

  const [views, setViewsState] = useState<WallView[]>(readViews);
  const [meta, setMetaState] = useState<ViewMetaMap>(readMeta);
  const viewsRef = useRef(views);
  const metaRef = useRef(meta);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  /** Yuklash davomida foydalanuvchi biror narsa o'zgartirsa, eski javob
   * uning o'zgarishini ustidan yozib yubormasin. */
  const mutationSeq = useRef(0);
  const lastLoadAt = useRef(0);
  const loading = useRef(false);

  const commit = useCallback((nextViews: WallView[], nextMeta: ViewMetaMap = metaRef.current) => {
    viewsRef.current = nextViews;
    metaRef.current = nextMeta;
    setViewsState(nextViews);
    setMetaState(nextMeta);
    writeJson(VIEWS_STORAGE_KEY, nextViews);
    writeJson(VIEWS_META_KEY, nextMeta);
  }, []);

  const markPending = useCallback((deletedId?: string) => {
    const pending = readPending();
    writeJson(VIEWS_PENDING_KEY, {
      dirty: true,
      deleted: deletedId ? [...new Set([...pending.deleted, deletedId])] : pending.deleted,
    });
  }, []);

  const applyServerItem = useCallback(
    (localId: string, item: ServerWallView) => {
      const parsed = fromServer(item);
      if (!parsed) return;
      const nextViews = viewsRef.current.map((view) => (view.id === localId ? parsed.view : view));
      const nextMeta = { ...metaRef.current, [parsed.view.id]: parsed.meta };
      if (localId !== parsed.view.id) {
        delete nextMeta[localId];
        optionsRef.current.onIdChange?.(localId, parsed.view.id);
      }
      commit(nextViews, nextMeta);
    },
    [commit],
  );

  const reject = useCallback((error: unknown, revert: (current: WallView[]) => WallView[]) => {
    commit(revert(viewsRef.current));
    const message = error instanceof Error && error.message ? error.message : "Ko'rinishni saqlab bo'lmadi";
    optionsRef.current.onError?.(message);
  }, [commit]);

  const load = useCallback(async () => {
    if (!remote || loading.current) return;
    loading.current = true;
    lastLoadAt.current = Date.now();
    const seq = mutationSeq.current;
    try {
      const flag = importedFlag(userName);
      let imported = false;
      try {
        imported = localStorage.getItem(flag) === '1';
      } catch {
        /* o'qib bo'lmasa — import qayta urinadi, u takrorga chidamli */
      }
      const pending = readPending();
      for (const id of pending.deleted) {
        try {
          await wallViewsApi.remove(id);
        } catch (error) {
          if (isOfflineError(error)) throw error;
        }
      }
      let items: ServerWallView[];
      const own = ownLocalViews(viewsRef.current, metaRef.current);
      if ((!imported || pending.dirty) && own.length > 0) {
        items = (await wallViewsApi.importViews(own)).items;
      } else {
        items = await wallViewsApi.list('view');
      }
      try {
        localStorage.setItem(flag, '1');
        localStorage.removeItem(VIEWS_PENDING_KEY);
      } catch {
        /* keyingi yuklashda import yana bir bor ketadi — zarari yo'q */
      }
      if (seq !== mutationSeq.current) return;
      const next = fromServerList(items);
      commit(next.views, next.meta);
    } catch {
      /* oflayn — kesh (localStorage) bilan ishlashda davom etamiz */
    } finally {
      loading.current = false;
    }
  }, [remote, userName, commit]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!remote) return;
    const onFocus = () => {
      if (Date.now() - lastLoadAt.current >= REFRESH_GAP_MS) void load();
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [remote, load]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === VIEWS_STORAGE_KEY || event.key === VIEWS_META_KEY || event.key === null) {
        const nextViews = readViews();
        const nextMeta = readMeta();
        viewsRef.current = nextViews;
        metaRef.current = nextMeta;
        setViewsState(nextViews);
        setMetaState(nextMeta);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const setViews = useCallback(
    (update: ViewsUpdate) => {
      const prev = viewsRef.current;
      const resolved = sanitizeViews(typeof update === 'function' ? update(prev) : update);
      const diff = diffViews(prev, resolved);
      commit(resolved);
      if (!remote) return;
      mutationSeq.current += 1;

      for (const view of diff.created) {
        wallViewsApi
          .create(view)
          .then((item) => applyServerItem(view.id, item))
          .catch((error) => {
            if (isOfflineError(error)) markPending();
            else reject(error, (current) => current.filter((item) => item.id !== view.id));
          });
      }
      for (const { before, after } of diff.updated) {
        wallViewsApi
          .update(after)
          .then((item) => applyServerItem(after.id, item))
          .catch((error) => {
            if (isOfflineError(error)) markPending();
            // Serverda yo'q (oflayn yaratilgan edi) — yaratib qo'yamiz.
            else if (error?.status === 404 && metaRef.current[after.id]?.mine !== false)
              wallViewsApi
                .create(after)
                .then((item) => applyServerItem(after.id, item))
                .catch((inner) => (isOfflineError(inner) ? markPending() : undefined));
            else reject(error, (current) => current.map((item) => (item.id === before.id ? before : item)));
          });
      }
      for (const { view, index } of diff.removed) {
        wallViewsApi.remove(view.id).catch((error) => {
          if (isOfflineError(error)) markPending(view.id);
          else if (error?.status !== 404)
            reject(error, (current) => {
              if (current.some((item) => item.id === view.id)) return current;
              const next = [...current];
              next.splice(Math.min(index, next.length), 0, view);
              return next;
            });
        });
      }
    },
    [remote, commit, applyServerItem, reject, markPending],
  );

  const info: StoredViewsInfo = { meta, remote };
  return [views, setViews, info] as const;
}

export type { ViewMeta };
