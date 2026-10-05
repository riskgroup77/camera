import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, Search, Users, X } from 'lucide-react';
import { Avatar, ProgressRing, cn, controlBase, focusRing } from '../../ui';
import { controlSizes } from '../../ui/cn';
import { getGroups, searchPeopleByName, situationPaths, type GroupStat, type PersonHit } from '../../lib/situationApi';
import { useDebouncedValue } from '../../lib/useDebouncedValue';

const MIN_QUERY = 2;
const GROUP_LIMIT = 6;
const PEOPLE_LIMIT = 6;

type Option =
  | { kind: 'group'; key: string; group: GroupStat }
  | { kind: 'person'; key: string; person: PersonHit };

/**
 * Tez o'tish: guruh nomi yoki talaba ism-familiyasi (JSHSHIR ham) bo'yicha.
 * Guruh — GET /api/situation/groups?search=, odam — POST
 * /api/students-staff/search (qidiruv matni URL/access log'ga tushmaydi).
 */
export function QuickSearch({
  date,
  withDate,
  className,
  autoFocus,
}: {
  date: string;
  /** Havolaga joriy sanani qo'shish (useViewDate().withDate). */
  withDate: (path: string) => string;
  className?: string;
  autoFocus?: boolean;
}) {
  const navigate = useNavigate();
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [groups, setGroups] = useState<GroupStat[]>([]);
  const [people, setPeople] = useState<PersonHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchedFor, setSearchedFor] = useState('');
  /** Ikkala so'rov ham yiqildi — "topilmadi" emas, xato ko'rsatiladi. */
  const [failed, setFailed] = useState(false);
  /** Faqat bittasi yiqildi: ro'yxat chiqadi, lekin u to'liq emasligi aytiladi
   *  (ilgari xato jimgina yutilib, qisqa ro'yxat to'liqdek ko'rinardi). */
  const [partial, setPartial] = useState<'group' | 'person' | null>(null);
  const text = useDebouncedValue(query.trim(), 250);

  useEffect(() => {
    if (text.length < MIN_QUERY) {
      setGroups([]);
      setPeople([]);
      setSearchedFor('');
      setSearching(false);
      setFailed(false);
      setPartial(null);
      return;
    }
    const controller = new AbortController();
    setSearching(true);
    Promise.allSettled([
      getGroups({ search: text, date }, { signal: controller.signal }),
      searchPeopleByName(text, { type: 'talaba', limit: PEOPLE_LIMIT }, { signal: controller.signal }),
    ]).then(([g, p]) => {
      if (controller.signal.aborted) return;
      setGroups(g.status === 'fulfilled' ? g.value.slice(0, GROUP_LIMIT) : []);
      setPeople(p.status === 'fulfilled' ? p.value.slice(0, PEOPLE_LIMIT) : []);
      setFailed(g.status === 'rejected' && p.status === 'rejected');
      setPartial(
        g.status === 'rejected' && p.status === 'fulfilled' ? 'group' : p.status === 'rejected' && g.status === 'fulfilled' ? 'person' : null,
      );
      setHighlight(0);
      setSearchedFor(text);
      setSearching(false);
    });
    return () => controller.abort();
  }, [text, date]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  const options = useMemo<Option[]>(
    () => [
      ...groups.map((group) => ({ kind: 'group' as const, key: `g:${group.name}`, group })),
      ...people.map((person) => ({ kind: 'person' as const, key: `p:${person.id}`, person })),
    ],
    [groups, people],
  );

  function choose(option: Option) {
    setOpen(false);
    setQuery('');
    if (option.kind === 'group') navigate(withDate(situationPaths.group(option.group.name)));
    else navigate(withDate(situationPaths.person(option.person.id)));
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && options.length) {
      event.preventDefault();
      // Ro'yxat yopiq edi — birinchi bosish uni ochadi va BIRINCHI natijani
      // belgilaydi (ilgari u birinchisini o'tkazib yuborardi).
      if (!open) {
        setOpen(true);
        setHighlight(0);
        return;
      }
      setHighlight((h) => (h + 1) % options.length);
    } else if (event.key === 'ArrowUp' && options.length) {
      event.preventDefault();
      setHighlight((h) => (h - 1 + options.length) % options.length);
    } else if (event.key === 'Enter' && open && options.length) {
      event.preventDefault();
      choose(options[Math.min(highlight, options.length - 1)]);
    } else if (event.key === 'Escape') {
      if (open) setOpen(false);
      else setQuery('');
    }
  }

  const trimmed = query.trim();
  const settled = open && !searching && trimmed.length >= MIN_QUERY && searchedFor === trimmed && options.length === 0;
  const showEmpty = settled && !failed;
  const showError = settled && failed;
  const showList = open && options.length > 0;

  return (
    <div ref={boxRef} className={cn('relative w-full sm:max-w-md', className)}>
      <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" />
      <input
        type="search"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder="Guruh yoki talabani qidirish…"
        aria-label="Guruh yoki talabani qidirish"
        role="combobox"
        aria-expanded={showList || showEmpty || showError}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList ? `${listId}-${highlight}` : undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        className={cn(controlBase, controlSizes.md, 'pl-9 pr-9 [&::-webkit-search-cancel-button]:hidden')}
      />
      {searching ? (
        <Loader2 size={15} aria-hidden="true" className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-subtle" />
      ) : (
        query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label="Qidiruvni tozalash"
            className={cn('absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-subtle hover:bg-surface-2 hover:text-fg', focusRing)}
          >
            <X size={14} aria-hidden="true" />
          </button>
        )
      )}

      {showList && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Topilganlar"
          className="absolute z-30 mt-1.5 max-h-[22rem] w-full animate-pop-in overflow-y-auto rounded-card border border-border bg-surface p-1 shadow-pop"
        >
          {partial && (
            <li role="presentation" className="px-2.5 py-1.5 text-[11px] text-warning">
              {partial === 'group' ? "Guruhlarni qidirib bo'lmadi — faqat talabalar ko'rsatilmoqda" : "Talabalarni qidirib bo'lmadi — faqat guruhlar ko'rsatilmoqda"}
            </li>
          )}
          {options.map((option, index) => {
            const active = index === highlight;
            const firstPerson = option.kind === 'person' && (index === 0 || options[index - 1].kind === 'group');
            const firstGroup = option.kind === 'group' && index === 0;
            return (
              <li key={option.key} role="presentation">
                {(firstGroup || firstPerson) && (
                  <p className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-subtle">
                    {firstGroup ? 'Guruhlar' : 'Talabalar'}
                  </p>
                )}
                <div
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => setHighlight(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(option)}
                  className={cn(
                    'flex cursor-pointer items-center gap-3 rounded-control px-2.5 py-2 text-sm',
                    active ? 'bg-surface-2' : 'hover:bg-surface-2',
                  )}
                >
                  {option.kind === 'group' ? (
                    <>
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-primary-soft text-primary">
                        <Users size={16} aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-fg">{option.group.name}</span>
                        <span className="block truncate text-xs text-muted">
                          {[option.group.faculty ?? 'Fakultetsiz', option.group.course ? `${option.group.course}-kurs` : null, `${option.group.total} talaba`]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <ProgressRing value={option.group.rate} size={34} thickness={3.5} />
                    </>
                  ) : (
                    <>
                      <Avatar name={option.person.fullName} src={option.person.biometricPhotoUrl} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-fg">{option.person.fullName}</span>
                        <span className="block truncate text-xs text-muted">
                          {[option.person.faculty, option.person.groupOrPosition].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      {option.person.biometricsStatus !== 'tasdiqlangan' && (
                        <span className="shrink-0 text-[11px] font-medium text-warning">yuzi yo'q</span>
                      )}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {showEmpty && (
        <p className="absolute z-30 mt-1.5 w-full rounded-card border border-border bg-surface px-3 py-3 text-center text-sm text-muted shadow-pop">
          «{trimmed}» bo'yicha guruh ham, talaba ham topilmadi
        </p>
      )}

      {showError && (
        <p role="alert" className="absolute z-30 mt-1.5 w-full rounded-card border border-danger/40 bg-surface px-3 py-3 text-center text-sm text-danger shadow-pop">
          Qidiruvni bajarib bo&apos;lmadi — ulanishni tekshirib, qayta urinib ko&apos;ring
        </p>
      )}
    </div>
  );
}
