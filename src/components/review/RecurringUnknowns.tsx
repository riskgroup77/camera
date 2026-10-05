import { useEffect, useState } from 'react';
import { calendarDateInTashkent } from '../../lib/uzDate';
import { Check, EyeOff, RefreshCw, Search, UserPlus } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
  assignRecurring,
  dismissRecurring,
  getRecurringUnknowns,
  pickPeople,
  sightingTime,
  type PersonPick,
  type RecurringUnknown,
} from '../../lib/notanishlarApi';
import { Button, Card, EmptyState, ErrorState, SkeletonCards, cn, useToast } from '../../ui';

/**
 * Takroriy notanishlar — bazada yuzi yo'q, lekin har kuni kameraga tushadigan
 * odamlar (camera-api/app/services/unknown_clusters.py).
 *
 * Bir odamning bir necha kundagi barcha yuzlari bitta kartada. Ism berilsa,
 * eng yirik yuz uning asosiy rasmi bo'ladi, qolganlari turli burchaklar
 * sifatida galereyaga qo'shiladi — ertasiga kamera uni o'zi taniydi.
 * Eng ko'p KUN ko'ringanlar birinchi: ularni tanitish davomatni eng ko'p
 * o'stiradi.
 */
export default function RecurringUnknowns({ onPending }: { onPending?: (n: number | null) => void }) {
  const toast = useToast();
  const [items, setItems] = useState<RecurringUnknown[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [minDays, setMinDays] = useState(1);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setItems(null);
    setError(null);
    getRecurringUnknowns({ kun: 14, min_kun: minDays, limit: 40 }, { signal: controller.signal })
      .then((result) => {
        setItems(result.items);
        onPending?.(result.items.length);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof ApiError ? err.message : "Ro'yxatni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [minDays, reload, onPending]);

  function remove(key: string) {
    setItems((current) => {
      const next = (current ?? []).filter((item) => item.key !== key);
      onPending?.(next.length);
      return next;
    });
  }

  async function assign(item: RecurringUnknown, personId: string) {
    try {
      const result = await assignRecurring(item.sightingIds, personId);
      toast.success(result.message);
      remove(item.key);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Biriktirib bo‘lmadi');
    }
  }

  async function skip(item: RecurringUnknown) {
    try {
      await dismissRecurring(item.sightingIds);
      remove(item.key);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Bajarib bo‘lmadi');
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-[13px] text-muted">
          Bazada yuzi yo‘q, lekin kameraga qayta-qayta tushayotgan odamlar. Ismini tanlang — kamera ertadan boshlab uni
          o‘zi taniydi.
        </p>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[12px] text-muted">
            Kamida
            <select
              value={minDays}
              onChange={(event) => setMinDays(Number(event.target.value))}
              className="h-8 rounded-control border border-border bg-surface px-2 text-[13px] text-fg"
              aria-label="Kamida necha kun ko'ringan"
            >
              {[1, 2, 3, 5].map((n) => (
                <option key={n} value={n}>
                  {n} kun
                </option>
              ))}
            </select>
          </label>
          <Button size="sm" icon={RefreshCw} onClick={() => setReload((n) => n + 1)}>
            Yangilash
          </Button>
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />
      ) : !items ? (
        <SkeletonCards count={6} />
      ) : items.length === 0 ? (
        <EmptyState title="Takroriy notanish yo‘q" description="Kameralar ko‘rgan hamma odam tanilgan yoki ko‘rib chiqilgan" />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <li key={item.key}>
              <RecurringCard item={item} onAssign={(personId) => assign(item, personId)} onSkip={() => skip(item)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecurringCard({
  item,
  onAssign,
  onSkip,
}: {
  item: RecurringUnknown;
  onAssign: (personId: string) => Promise<void>;
  onSkip: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  const [main, ...rest] = item.cropUrls;

  return (
    <Card className="flex h-full flex-col gap-2.5 p-3">
      <div className="flex gap-2">
        <div className="aspect-[3/4] w-28 shrink-0 overflow-hidden rounded-control bg-surface-2">
          {main ? <img src={main} alt="Eng aniq yuz" className="h-full w-full object-cover" loading="lazy" /> : null}
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <b className="text-[20px] tabular-nums text-fg">{item.days}</b>
            <span className="text-[12px] text-muted">kun · {item.hits} marta · {item.facePx} px</span>
          </div>
          <p className="line-clamp-2 text-[12px] text-muted">{item.cameras.join(', ') || '—'}</p>
          <p className="text-[11px] text-subtle">
            Oxirgi: {calendarDateInTashkent(new Date(item.lastSeenAt)).split('-').reverse().join('.')} {sightingTime(item.lastSeenAt)}
          </p>
          {rest.length > 0 && (
            <div className="flex gap-1 pt-1">
              {rest.slice(0, 4).map((url) => (
                <img key={url} src={url} alt="" className="h-10 w-8 rounded object-cover" loading="lazy" />
              ))}
            </div>
          )}
        </div>
      </div>

      {item.hints.length > 0 && (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-subtle">Bu kimdir emasmi?</p>
          {item.hints.map((hint) => (
            <button
              key={hint.personId}
              type="button"
              disabled={busy}
              onClick={() => run(() => onAssign(hint.personId))}
              className="flex w-full items-center gap-2 rounded-control border border-border px-2 py-1.5 text-left hover:border-primary hover:bg-primary-soft disabled:opacity-50"
            >
              <Check size={13} className="shrink-0 text-success" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{hint.fullName}</span>
              <span className="shrink-0 text-[11px] text-muted">
                {hint.groupOrPosition} · {Math.round(hint.similarity * 100)}%
              </span>
            </button>
          ))}
        </div>
      )}

      <PersonSearch disabled={busy} onPick={(person) => run(() => onAssign(person.id))} />

      <div className="mt-auto flex justify-end">
        <Button size="sm" variant="ghost" icon={EyeOff} disabled={busy} onClick={() => run(onSkip)}>
          O‘tkazish
        </Button>
      </div>
    </Card>
  );
}

function PersonSearch({ disabled, onPick }: { disabled: boolean; onPick: (person: PersonPick) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PersonPick[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const text = query.trim();
    // Yangi qidiruv boshlandi — oldingi natijalar (boshqa ism uchun) darhol
    // olib tashlanadi: aks holda yuz eski ro'yxatdagi odamga biriktirilishi mumkin edi.
    setResults([]);
    setFailed(false);
    if (text.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      pickPeople(text, 6, { signal: controller.signal })
        .then(setResults)
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  return (
    <div className="space-y-1">
      <label className="flex items-center gap-1.5 rounded-control border border-border bg-surface px-2">
        <Search size={13} aria-hidden="true" className="text-subtle" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ism familiya bo‘yicha qidirish"
          aria-label="Kimligini qidirish"
          className="h-8 min-w-0 flex-1 bg-transparent text-[13px] outline-none"
        />
      </label>
      {failed && <p className="text-[11px] text-danger">Qidirib bo‘lmadi — qayta urinib ko‘ring</p>}
      {results.length > 0 && (
        <ul className="max-h-44 overflow-y-auto rounded-control border border-border">
          {results.map((person) => (
            <li key={person.id}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onPick(person)}
                className={cn('flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-primary-soft disabled:opacity-50')}
              >
                <UserPlus size={13} className="shrink-0 text-primary" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-fg">{person.fullName}</span>
                  <span className="block truncate text-[11px] text-muted">{person.groupOrPosition}</span>
                </span>
                {person.biometricsStatus === 'tasdiqlangan' && (
                  <span className="shrink-0 text-[10px] text-success">yuzi bor</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
