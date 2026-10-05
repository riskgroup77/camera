import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Yorliq yonidagi son (masalan "Yangi 12"). */
  count?: number | null;
  disabled?: boolean;
}

/** URL'dagi qiymat ro'yxatda bo'lsa — o'sha, aks holda standart (yoki birinchi). */
export function resolveTab<T extends string>(raw: string | null, tabs: readonly TabItem<T>[], defaultTab?: T): T | undefined {
  const enabled = tabs.filter((tab) => !tab.disabled);
  const match = enabled.find((tab) => tab.id === raw);
  if (match) return match.id;
  if (defaultTab && enabled.some((tab) => tab.id === defaultTab)) return defaultTab;
  return enabled[0]?.id;
}

/** Tabni `?tab=` bilan tanlangan holda qaytaradigan URL parametrlari.
 *  Standart tab URL'dan olib tashlanadi (toza manzil). */
export function nextTabParams(current: URLSearchParams, id: string, defaultId: string | undefined, param = 'tab'): URLSearchParams {
  const next = new URLSearchParams(current);
  if (id === defaultId) next.delete(param);
  else next.set(param, id);
  return next;
}

export interface UrlTabOptions<T extends string> {
  /** URL parametr nomi (standart "tab"). */
  param?: string;
  /** Standart tab (standart: birinchi faol tab). */
  defaultTab?: T;
}

/** Joriy tab URL'da (`?tab=`) saqlanadi: havola bilan ulashiladi, orqaga
 *  tugmasi va sahifa yangilanishi tabni yo'qotmaydi. `Page tabs=` ham xuddi
 *  shu hookni ishlatadi — sahifa kontenti shu qiymat bo'yicha chiziladi. */
export function useUrlTab<T extends string>(tabs: readonly TabItem<T>[], options: UrlTabOptions<T> = {}): [T, (id: T) => void] {
  const { param = 'tab', defaultTab } = options;
  const [params, setParams] = useSearchParams();
  const active = resolveTab(params.get(param), tabs, defaultTab) as T;
  const fallback = resolveTab(null, tabs, defaultTab);

  const setActive = useCallback(
    (id: T) => {
      setParams((prev) => nextTabParams(prev, id, fallback, param), { replace: true });
    },
    [setParams, fallback, param],
  );

  return [active, setActive];
}
