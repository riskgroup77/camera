import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'motion/react';
import { Building2, Cctv, CornerDownLeft, Search, SearchX, UserRound, type LucideIcon } from 'lucide-react';
import { api, buildQuery, isAbortError, type Page as ApiPage } from '../lib/apiClient';
import { isBackendConfigured } from '../lib/config';
import { highlight, matchText, rankItems, type MatchRange } from '../lib/search';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import { searchPeopleByName, type KafedraStat } from '../lib/situationApi';
import { cn } from '../ui';
import { useDialog } from '../ui/internal/useDialog';
import { EASE, reducedMotion } from './motion';

/**
 * KONSOL PALITRASI (Ctrl/⌘+K).
 *
 * Nega `layouts/shell/CommandPalette.tsx` emas: undagi har bir tanlov
 * `navigate(to)` — ya'ni SAHIFAGA o'tish, va bandlar menyu bo'limlaridan
 * tuziladi. Konsolda manzil o'zgarmaydi (konsol.md, 2-qoida): bu yerdagi
 * tanlov PANELNI ochadi. Qidiruv mantig'i esa o'sha joydan — `lib/search`
 * (matn moslash, baholash, ajratib ko'rsatish) qayta yozilmadi.
 */

/** Tanlov: panel va undagi aniq obyekt (kamera kattalashadi, bo'linma
 *  ichi ochiladi). Shaxs — uning sahifasi (konsolda shaxs paneli yo'q). */
export type PaletteTarget =
  | { panel: 'units'; id?: string | null }
  | { panel: 'cameras'; id?: string }
  | { panel: 'person'; id: string };

type Kind = 'unit' | 'camera' | 'person';

interface Row {
  key: string;
  kind: Kind;
  title: string;
  subtitle?: string;
  icon: LucideIcon;
  code: string;
  ranges: MatchRange[];
  target: PaletteTarget;
}

const KIND_LABEL: Record<Kind, string> = {
  unit: "Bo'linmalar",
  camera: 'Kameralar',
  person: 'Shaxslar',
};

const KIND_CODE: Record<Kind, string> = { unit: 'BLM', camera: 'KMR', person: 'SHX' };

interface PublicCamera {
  id: string;
  name: string;
  building: string;
  zone: string;
}

/** Qidiruv kaliti bo'yicha bekor qilinadigan so'rov. */
function useRemote<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<{ key: string | null; data: T | null; loading: boolean }>({ key: null, data: null, loading: false });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  useEffect(() => {
    if (!key) {
      setState({ key: null, data: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((prev) => ({ key, data: prev.key === key ? prev.data : null, loading: true }));
    fetcherRef
      .current(controller.signal)
      .then((data) => !controller.signal.aborted && setState({ key, data, loading: false }))
      .catch((err: unknown) => {
        if (isAbortError(err) || controller.signal.aborted) return;
        setState({ key, data: null, loading: false });
      });
    return () => controller.abort();
  }, [key]);
  return { data: state.key === key ? state.data : null, loading: state.loading };
}

export interface ConsolePaletteProps {
  open: boolean;
  onClose: () => void;
  /** Konsol allaqachon olgan bo'linmalar — qayta so'ralmaydi. */
  units: readonly KafedraStat[];
  onOpen: (target: PaletteTarget) => void;
  /** Shaxslar qidirilsinmi (davomat huquqi bo'lsa). */
  people?: boolean;
  /** Kameralar qidirilsinmi (jonli ko'rish huquqi bo'lsa). */
  cameras?: boolean;
}

export default function ConsolePalette({ open, ...props }: ConsolePaletteProps) {
  if (!open) return null;
  return createPortal(<Dialog {...props} />, document.body);
}

function Dialog({ onClose, units, onOpen, people = false, cameras: withCameras = true }: Omit<ConsolePaletteProps, 'open'>) {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  useDialog(true, onClose, panelRef, inputRef);

  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const debounced = useDebouncedValue(query.trim(), 200);
  const remoteQ = isBackendConfigured && debounced.length >= 2 ? debounced : '';

  const cameras = useRemote(withCameras && remoteQ ? `c:${remoteQ}` : null, (signal) =>
    api.get<ApiPage<PublicCamera>>(`/api/public/cameras${buildQuery({ search: remoteQ, pageSize: 5 })}`, null, { signal }),
  );
  const persons = useRemote(people && remoteQ ? `p:${remoteQ}` : null, (signal) => searchPeopleByName(remoteQ, { limit: 6 }, { signal }));

  const rows: Row[] = useMemo(() => {
    const q = query.trim();
    const mk = (kind: Kind, id: string, title: string, target: PaletteTarget, subtitle?: string, icon?: LucideIcon): Row => ({
      key: `${kind}:${id}`,
      kind,
      title,
      subtitle,
      icon: icon ?? ICONS[kind],
      code: KIND_CODE[kind],
      ranges: q ? (matchText(q, title)?.ranges ?? []) : [],
      target,
    });

    const out: Row[] = [];
    const unitItems = q ? rankItems(q, units.map((unit) => ({ ...unit, title: unit.name })), 6).map((hit) => hit.item) : units.slice(0, 4);
    out.push(...unitItems.map((unit) => mk('unit', unit.id ?? unit.name, unit.name, { panel: 'units', id: unit.id }, `${unit.staffTotal} xodim`)));

    out.push(
      ...(persons.data ?? []).map((person) =>
        mk('person', person.id, person.fullName, { panel: 'person', id: person.id }, person.groupOrPosition ?? undefined),
      ),
    );

    out.push(
      ...(cameras.data?.items ?? []).map((camera) =>
        mk('camera', camera.id, camera.name, { panel: 'cameras', id: camera.id }, [camera.building, camera.zone].filter(Boolean).join(' · ')),
      ),
    );
    return out;
  }, [query, units, cameras.data, persons.data]);

  const loading = cameras.loading || persons.loading || (isBackendConfigured && query.trim().length >= 2 && query.trim() !== debounced);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    if (active >= rows.length) setActive(Math.max(0, rows.length - 1));
  }, [rows.length, active]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const choose = useCallback(
    (row: Row) => {
      onClose();
      onOpen(row.target);
    },
    [onClose, onOpen],
  );

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (rows.length ? (i + 1) % rows.length : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (rows.length ? (i - 1 + rows.length) % rows.length : 0));
    } else if (event.key === 'Enter') {
      const row = rows[active];
      if (row) {
        event.preventDefault();
        choose(row);
      }
    }
  }

  let index = -1;
  let lastKind: Kind | null = null;
  const still = reducedMotion();

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center px-3 pt-[12vh]">
      <motion.div
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: still ? 0 : 0.18, ease: EASE }}
        onClick={onClose}
        aria-hidden="true"
        className="absolute inset-0 bg-slate-900/25 backdrop-blur-[2px]"
      />
      <motion.div
        ref={panelRef}
        initial={still ? false : { opacity: 0, y: -10, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: still ? 0 : 0.24, ease: EASE }}
        role="dialog"
        aria-modal="true"
        aria-label="Konsol qidiruvi"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="glass relative flex max-h-[min(32rem,72vh)] w-full max-w-xl flex-col overflow-hidden rounded-[8px] outline-none"
      >
        <div className="flex shrink-0 items-center gap-2.5 border-b border-white/70 px-3">
          <Search size={16} aria-hidden="true" className="shrink-0 text-subtle" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={people ? "Shaxs, bo'linma yoki kamera" : "Bo'linma yoki kamera"}
            aria-label="Konsol qidiruvi"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
            className="h-11 min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-subtle"
          />
          <kbd className="intel-code hidden border border-white/80 px-1.5 py-0.5 text-[10px] text-muted sm:inline">ESC</kbd>
        </div>

        <div ref={listRef} id={listId} role="listbox" aria-label="Natijalar" className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
          {rows.length === 0 && (
            <div className="flex flex-col items-center px-6 py-8 text-center">
              <SearchX size={18} aria-hidden="true" className="mb-2 text-subtle" />
              <p className="text-[13px] font-semibold">Hech narsa topilmadi</p>
              <p className="intel-micro mt-1">{loading ? 'Qidirilmoqda…' : 'Boshqacha yozib ko‘ring'}</p>
            </div>
          )}
          {rows.map((row) => {
            index += 1;
            const i = index;
            const selected = i === active;
            const Icon = row.icon;
            const header = row.kind !== lastKind ? row.kind : null;
            lastKind = row.kind;
            return (
              <div key={row.key}>
                {header && <p className="intel-micro px-3 pb-0.5 pt-2">{KIND_LABEL[header]}</p>}
                <div
                  data-index={i}
                  role="option"
                  aria-selected={selected}
                  onMouseMove={() => active !== i && setActive(i)}
                  onClick={() => choose(row)}
                  className={cn(
                    'relative flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-[13px]',
                    selected ? 'bg-white/80 text-primary' : 'text-fg',
                  )}
                >
                  <span className={cn('intel-code w-[26px] shrink-0 text-[10px]', selected ? 'text-primary' : 'text-subtle')} aria-hidden="true">
                    {row.code}
                  </span>
                  <Icon size={15} aria-hidden="true" className={cn('shrink-0', selected ? 'text-primary' : 'text-muted')} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">
                      {highlight(row.title, row.ranges).map((part, partIndex) =>
                        part.match ? (
                          <mark key={partIndex} className="bg-primary/15 px-px font-semibold text-primary">
                            {part.text}
                          </mark>
                        ) : (
                          <span key={partIndex}>{part.text}</span>
                        ),
                      )}
                    </span>
                    {row.subtitle && <span className="intel-micro block truncate">{row.subtitle}</span>}
                  </span>
                  {selected && <CornerDownLeft size={13} aria-hidden="true" className="shrink-0 text-primary" />}
                </div>
              </div>
            );
          })}
        </div>

        {!isBackendConfigured && (
          <p className="intel-micro shrink-0 border-t border-white/70 px-3 py-1.5">Server ulanmagan — faqat bo‘limlar va bo‘linmalar</p>
        )}
      </motion.div>
    </div>
  );
}

const ICONS: Record<Kind, LucideIcon> = { unit: Building2, camera: Cctv, person: UserRound };
