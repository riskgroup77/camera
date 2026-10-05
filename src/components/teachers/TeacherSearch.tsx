import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, UserSearch } from 'lucide-react';
import { Avatar, SearchInput, cn } from '../../ui';
import { isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { situationPaths } from '../../lib/situationApi';
import { getTeachersDay, searchStaff } from '../../lib/teachersApi';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import { useViewDate } from '../../lib/viewDate';

interface Hit {
  id: string;
  fullName: string;
  photoUrl: string | null;
  subtitle: string;
}

/** O'qituvchini ism bo'yicha topib, profiliga (/shaxs/:id) o'tish.
 *  Reestr huquqi bo'lsa — barcha xodimlar orasidan; aks holda shu kuni
 *  kameralar tanigan yoki darsi bor xodimlar orasidan. */
export function TeacherSearch({ className }: { className?: string }) {
  const { role } = useAuth();
  const { can } = usePermissions();
  const { date, withDate } = useViewDate();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebouncedValue(query.trim(), 250);
  const listId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const fullRegistry = can('registerPeople', role);

  useEffect(() => {
    if (debounced.length < 2) {
      setHits([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const request = fullRegistry
      ? searchStaff(debounced, 8, { signal: controller.signal }).then((rows) =>
          rows.map((r) => ({ id: r.id, fullName: r.fullName, photoUrl: r.biometricPhotoUrl ?? null, subtitle: [r.groupOrPosition, r.faculty].filter(Boolean).join(' · ') })),
        )
      : getTeachersDay({ date, search: debounced }, { signal: controller.signal }).then((rows) =>
          rows.slice(0, 8).map((r) => ({ id: r.id, fullName: r.fullName, photoUrl: null, subtitle: [r.unit, r.faculty].filter(Boolean).join(' · ') })),
        );
    request
      .then((list) => {
        setHits(list);
        setActive(0);
      })
      .catch((err) => {
        if (!isAbortError(err)) setHits([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [debounced, fullRegistry, date]);

  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, []);

  function go(hit: Hit) {
    setOpen(false);
    setQuery('');
    navigate(withDate(situationPaths.person(hit.id)));
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!open || hits.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (i + 1) % hits.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (i - 1 + hits.length) % hits.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      go(hits[active]);
    }
  }

  function onKeyDownCapture(event: KeyboardEvent<HTMLDivElement>) {
    // Escape ro'yxatni yopadi (SearchInput'ning "Esc — tozalash"idan oldin:
    // avval ochiq ro'yxat yopilsin, yozilgan matn saqlansin).
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
  }

  const showPanel = open && debounced.length >= 2;

  return (
    <div
      ref={wrapRef}
      className={cn('relative w-full sm:w-80', className)}
      onKeyDownCapture={onKeyDownCapture}
      onKeyDown={onKeyDown}
      onFocus={() => setOpen(true)}
    >
      {/* Ekran o'quvchi uchun: nechta natija topilgani ovoz chiqarib o'qiladi. */}
      <p className="sr-only" role="status" aria-live="polite">
        {showPanel ? (loading ? 'Qidirilmoqda' : `${hits.length} ta xodim topildi`) : ''}
      </p>
      <SearchInput
        value={query}
        onChange={(value) => {
          setQuery(value);
          setOpen(true);
        }}
        placeholder="O'qituvchini qidirish…"
        ariaLabel="O'qituvchini ism bo'yicha qidirish"
        className="sm:max-w-none"
      />
      {showPanel && (
        <div
          id={listId}
          role="listbox"
          aria-label="Topilgan o'qituvchilar"
          className="absolute left-0 right-0 top-full z-30 mt-1.5 max-h-80 overflow-y-auto rounded-card border border-border bg-surface p-1 shadow-pop"
        >
          {loading && hits.length === 0 && (
            <div className="flex items-center gap-2 px-3 py-3 text-[13px] text-muted">
              <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Qidirilmoqda…
            </div>
          )}
          {!loading && hits.length === 0 && (
            <div className="flex items-center gap-2 px-3 py-3 text-[13px] text-muted">
              <UserSearch size={14} aria-hidden="true" /> Hech kim topilmadi
            </div>
          )}
          {hits.map((hit, index) => (
            <button
              key={hit.id}
              type="button"
              role="option"
              aria-selected={index === active}
              onMouseEnter={() => setActive(index)}
              onClick={() => go(hit)}
              className={cn('flex w-full items-center gap-3 rounded-control px-2.5 py-2 text-left', index === active ? 'bg-surface-2' : 'hover:bg-surface-2')}
            >
              <Avatar name={hit.fullName} src={hit.photoUrl} size="sm" />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-fg">{hit.fullName}</span>
                {hit.subtitle && <span className="block truncate text-xs text-muted">{hit.subtitle}</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
