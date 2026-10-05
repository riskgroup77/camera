/**
 * Konsol filtri — SANA va KIM (xodim / talaba / hammasi).
 *
 * Filtr URL'da yashaydi (`?sana=…&kim=…`), shuning uchun ko'rinishni
 * havola qilib yuborish mumkin. Lekin u MARSHRUTNI o'zgartirmaydi:
 * `setSearchParams(..., { replace: true })` bir xil route elementini
 * qayta chizadi — konsol qayta yuklanmaydi (Panel'dagi `layoutId`
 * animatsiyasi ham uzilmaydi).
 *
 * Sana qismi `useViewDate` (src/lib/viewDate.ts) — butun tizimda bitta
 * "ko'rilayotgan sana" parametri bor, konsol o'ziniki yasamaydi.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useViewDate, type ViewDate } from '../lib/viewDate';

/** Kim ko'rilmoqda. API'dagi `PersonType` bilan bir xil yoziladi. */
export type Scope = 'hammasi' | 'xodim' | 'talaba';

export const SCOPE_PARAM = 'kim';

/** Filtr tugmalari shu tartibda chiziladi. */
export const SCOPES: readonly Scope[] = ['hammasi', 'xodim', 'talaba'];

export const SCOPE_LABEL: Record<Scope, string> = {
  hammasi: 'Hammasi',
  xodim: 'Xodimlar',
  talaba: 'Talabalar',
};

/** Noma'lum yoki bo'sh qiymat — "hammasi" (standart). */
export function parseScope(raw: string | null | undefined): Scope {
  return SCOPES.find((scope) => scope === raw) ?? 'hammasi';
}

/** Parametrlarni yangi `kim` bilan qaytaradi. Standart qiymat
 *  parametrsiz yoziladi — manzil toza qoladi. */
export function nextScopeParams(current: URLSearchParams, scope: Scope): URLSearchParams {
  const next = new URLSearchParams(current);
  if (parseScope(scope) === 'hammasi') next.delete(SCOPE_PARAM);
  else next.set(SCOPE_PARAM, scope);
  return next;
}

/** Filtr xodimni o'z ichiga oladimi. */
export function includesStaff(scope: Scope): boolean {
  return scope !== 'talaba';
}

/** Filtr talabani o'z ichiga oladimi. */
export function includesStudents(scope: Scope): boolean {
  return scope !== 'xodim';
}

export interface ConsoleFilter extends ViewDate {
  scope: Scope;
  setScope: (scope: Scope) => void;
}

export function useConsoleFilter(): ConsoleFilter {
  const viewDate = useViewDate();
  const [params, setParams] = useSearchParams();
  const scope = parseScope(params.get(SCOPE_PARAM));

  const setScope = useCallback(
    (next: Scope) => setParams((prev) => nextScopeParams(prev, next), { replace: true }),
    [setParams],
  );

  return useMemo(() => ({ ...viewDate, scope, setScope }), [viewDate, scope, setScope]);
}
