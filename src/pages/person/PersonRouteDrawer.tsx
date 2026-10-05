import { useEffect, useState } from 'react';
import { MonitorPlay, Route } from 'lucide-react';
import { ButtonLink, DatePicker, Drawer, EmptyState, ErrorState, Skeleton } from '../../ui';
import { isAbortError } from '../../lib/apiClient';
import { todayInTashkent } from '../../lib/uzDate';
import {
  getPersonRoute,
  liveLink,
  similarityPercent,
  stopDuration,
  stopPlace,
  stopTimeRange,
  type PersonRoute,
} from '../../lib/personLocatorApi';

export interface RouteTarget {
  id: string;
  fullName: string;
  /** Oxirgi ko'rilgan payt — yo'l shu kundan ochiladi (bugun bo'lmasa ham). */
  lastSeenAt?: string | null;
}

function initialDay(target: RouteTarget | null): string {
  if (target?.lastSeenAt) {
    const date = new Date(target.lastSeenAt);
    if (!Number.isNaN(date.getTime())) return todayInTashkent(date);
  }
  return todayInTashkent();
}

/** Odamning bir kunlik yo'li: kameralar bo'yicha to'xtashlar, har biridan
 *  arxivga (shu paytga) va jonli ko'rinishga o'tish. */
export function PersonRouteDrawer({ target, onClose }: { target: RouteTarget | null; onClose: () => void }) {
  // Kalit orqali qayta o'rnatiladi — boshqa odam ochilganda sana uning
  // oxirgi ko'rilgan kuniga qaytadi.
  return (
    <Drawer open={target !== null} onClose={onClose} title="Yo‘li" subtitle={target?.fullName} size="md">
      {target && <RouteBody key={target.id} target={target} />}
    </Drawer>
  );
}

function RouteBody({ target }: { target: RouteTarget }) {
  const [day, setDay] = useState(() => initialDay(target));
  const [route, setRoute] = useState<PersonRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getPersonRoute(target.id, day, controller.signal)
      .then(setRoute)
      .catch((err) => { if (!isAbortError(err)) setError((err as Error).message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [target.id, day, attempt]);

  const stops = route?.day === day ? route.stops : [];

  return (
    <div className="flex flex-col gap-3">
      <DatePicker value={day} onChange={setDay} size="sm" />
      {loading && <div className="space-y-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>}
      {error && <ErrorState message={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {!loading && !error && stops.length === 0 && <EmptyState icon={Route} title="Bu kuni ko‘rilmagan" compact />}
      {!loading && !error && stops.length > 0 && (
        <ol className="relative ml-2 border-l-2 border-border pl-4">
          {stops.map((stop, index) => {
            const place = stopPlace(stop);
            const duration = stopDuration(stop);
            return (
              <li key={`${stop.startedAt}-${index}`} className="relative pb-4 last:pb-0">
                <span className="absolute -left-[23px] top-1 h-3 w-3 rounded-full border-2 border-surface bg-primary" aria-hidden="true" />
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="intel-code text-[13px] font-semibold text-fg">{stopTimeRange(stop)}</span>
                  {duration && <span className="text-[11px] text-muted">{duration}</span>}
                </div>
                <p className="truncate text-[13px] font-medium text-fg">{stop.cameraName ?? 'O‘chirilgan kamera'}</p>
                {place && <p className="truncate text-[12px] text-muted">{place}</p>}
                <p className="text-[11px] text-muted">{stop.count} marta · {similarityPercent(stop.bestSimilarity)}</p>
                {stop.cameraId && (
                  <div className="mt-1.5 flex gap-1.5">
                    <ButtonLink to={liveLink(stop.cameraId)} icon={MonitorPlay} size="sm" variant="ghost">Jonli</ButtonLink>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
