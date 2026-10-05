import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { CounterKey } from '../components/situation/StatusCounters';

/**
 * Nazorat tanlovi — URL'da (havolani ulashish mumkin, qayta yuklanganda
 * saqlanadi): qaysi guruh va jadval qaysi holat bo'yicha filtrlangan.
 * Chap jadval ham, o'ngdagi guruh ma'lumoti ham shu bitta tanlovga bo'ysunadi.
 */

export const GROUP_PARAM = 'guruh';
export const STATUS_PARAM = 'holat';
export const WHO_PARAM = 'toifa';

export type Who = 'talaba' | 'xodim';

const COUNTER_KEYS: readonly CounterKey[] = [
  'hammasi', 'kelgan', 'kech_keldi', 'kelmadi', 'kutilmoqda', 'yuzsiz', 'darsda', 'darsda_emas',
];

export function parseCounter(raw: string | null): CounterKey {
  return raw && (COUNTER_KEYS as readonly string[]).includes(raw) ? (raw as CounterKey) : 'hammasi';
}

export interface NazoratSelection {
  /** Talabalar yoki o'qituvchi/xodimlar. */
  who: Who;
  group: string;
  status: CounterKey;
  setWho: (who: Who) => void;
  setGroup: (group: string) => void;
  setStatus: (status: CounterKey) => void;
}

export function useNazoratSelection(): NazoratSelection {
  const [params, setParams] = useSearchParams();
  const group = params.get(GROUP_PARAM) ?? '';
  const status = parseCounter(params.get(STATUS_PARAM));
  const who: Who = params.get(WHO_PARAM) === 'xodim' ? 'xodim' : 'talaba';

  const setWho = useCallback(
    (next: Who) =>
      setParams(
        (current) => {
          const out = new URLSearchParams(current);
          if (next === 'xodim') out.set(WHO_PARAM, next);
          else out.delete(WHO_PARAM);
          out.delete(GROUP_PARAM);
          out.delete(STATUS_PARAM);
          return out;
        },
        { replace: true },
      ),
    [setParams],
  );

  const setGroup = useCallback(
    (next: string) =>
      setParams(
        (current) => {
          const out = new URLSearchParams(current);
          if (next) out.set(GROUP_PARAM, next);
          else out.delete(GROUP_PARAM);
          out.delete(STATUS_PARAM);
          return out;
        },
        { replace: true },
      ),
    [setParams],
  );

  const setStatus = useCallback(
    (next: CounterKey) =>
      setParams(
        (current) => {
          const out = new URLSearchParams(current);
          if (next === 'hammasi') out.delete(STATUS_PARAM);
          else out.set(STATUS_PARAM, next);
          return out;
        },
        { replace: true },
      ),
    [setParams],
  );

  return { who, group, status, setWho, setGroup, setStatus };
}
