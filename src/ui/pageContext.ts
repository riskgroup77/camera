import { createContext, useContext } from 'react';

export interface Crumb {
  label: string;
  /** Oxirgi (joriy) elementda bo'lmaydi. */
  to?: string;
}

export interface PageMeta {
  title: string;
  crumbs?: Crumb[];
}

export interface ShellContextValue {
  /** Page o'z sarlavhasi va non-yo'lini (breadcrumbs) qobiqqa beradi. */
  setPageMeta: (meta: PageMeta | null) => void;
  /** Taqdimot rejimi (devor ekrani): qorong'i, yon panelsiz, to'liq ekran. */
  presentation: boolean;
  /** Qobiq ichidami (testlarda va login sahifalarida — yo'q). */
  inShell: boolean;
}

export const ShellContext = createContext<ShellContextValue>({
  setPageMeta: () => {},
  presentation: false,
  inShell: false,
});

/** Sahifalar uchun: taqdimot rejimi yoqilganmi va h.k. */
export function useShell(): ShellContextValue {
  return useContext(ShellContext);
}
