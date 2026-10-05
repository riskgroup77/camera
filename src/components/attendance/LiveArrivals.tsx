import { Link } from 'react-router-dom';
import { Radio } from 'lucide-react';
import { Avatar, Badge, Card, CardHeader, StatusBadge, StatusDot, cn, focusRing } from '../../ui';

export interface ArrivalItem {
  personId: string;
  fullName: string | null;
  photoUrl?: string | null;
  unit?: string | null;
  status: string;
  checkIn: string | null;
}

/**
 * Hozirgina kamera orqali davomatga yozilganlar. Dastlab serverdagi oxirgi
 * kelishlar, keyin WebSocket (attendance_recorded) orqali jonli qo'shiladi —
 * sahifani yangilash shart emas.
 */
export function LiveArrivals({
  items,
  linkFor,
  live,
  className,
}: {
  items: ArrivalItem[];
  linkFor: (personId: string) => string;
  /** Jonli ulanish faol (bugungi sana). */
  live: boolean;
  className?: string;
}) {
  return (
    <Card className={cn('flex flex-col', className)}>
      <CardHeader
        title="Hozirgina kelganlar"
        subtitle={live ? "Kamera tanishi bilan shu yerda" : "Shu kunning oxirgi kelishlari"}
        icon={Radio}
        actions={live ? <Badge tone="success" className="gap-2"><StatusDot tone="success" pulse />Jonli</Badge> : undefined}
      />
      {items.length === 0 ? (
        <p className="rounded-control bg-surface-2 px-3 py-3 text-[13px] text-muted">Hali hech kim qayd etilmagan.</p>
      ) : (
        <ul className="-mx-2 flex flex-col" aria-live="polite">
          {items.map((item) => (
            <li key={`${item.personId}-${item.checkIn}`} className="animate-fade-in">
              <Link to={linkFor(item.personId)} className={cn('flex items-center gap-3 rounded-control px-2 py-2 hover:bg-surface-2', focusRing)}>
                <Avatar name={item.fullName ?? '?'} src={item.photoUrl} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-fg">{item.fullName ?? "Noma'lum"}</span>
                  {item.unit && <span className="block truncate text-xs text-muted">{item.unit}</span>}
                </span>
                <StatusBadge status={item.status} time={item.checkIn} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
