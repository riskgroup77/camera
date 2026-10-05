import { cn } from './cn';

/** Yuklanish joy egallovchisi — spinner o'rniga shakl: sahifa sakramaydi. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton-shimmer rounded-[1px] bg-surface-3', className)} aria-hidden="true" />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn('h-3', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** StatTile'lar qatori shaklida. */
export function SkeletonTiles({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div className={cn('grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4', className)} aria-busy="true" aria-label="Yuklanmoqda">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-card border border-border bg-surface p-3">
          <Skeleton className="h-2.5 w-1/2" />
          <Skeleton className="mt-2.5 h-6 w-1/3" />
          <Skeleton className="mt-2.5 h-1.5 w-full" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCard({ className, lines = 4 }: { className?: string; lines?: number }) {
  return (
    <div className={cn('rounded-card border border-border bg-surface p-3', className)} aria-busy="true" aria-label="Yuklanmoqda">
      <Skeleton className="h-4 w-40" />
      <SkeletonText lines={lines} className="mt-4" />
    </div>
  );
}

/** Karta to'ridagi yuklanish holati (fakultetlar, guruhlar, kafedralar).
 *
 *  Ilgari har sahifa `Array.from(...).map(<Skeleton className="h-44 …" />)`ni
 *  o'zi yozardi — balandligi har joyda boshqacha va `aria-busy` yo'q edi. */
export function SkeletonCards({
  count = 4,
  height = 'h-44',
  className = 'md:grid-cols-2',
}: {
  count?: number;
  /** Tailwind balandlik sinfi (masalan "h-36"). */
  height?: string;
  className?: string;
}) {
  return (
    <div className={cn('grid gap-2', className)} aria-busy="true" aria-label="Yuklanmoqda">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={cn(height, 'rounded-card')} />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 6, columns = 5, className }: { rows?: number; columns?: number; className?: string }) {
  const grid = { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` };
  return (
    <div className={cn('overflow-hidden rounded-card border border-border bg-surface', className)} aria-busy="true" aria-label="Yuklanmoqda">
      <div className="grid gap-3 border-b-2 border-border-strong bg-surface-2 px-2.5 py-2" style={grid}>
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} className="h-2.5 w-2/3" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="grid gap-3 border-b border-border px-2.5 py-2 last:border-b-0" style={grid}>
          {Array.from({ length: columns }).map((_, c) => (
            <Skeleton key={c} className={cn('h-3', c === 0 ? 'w-5/6' : 'w-1/2')} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Sahifa bo'lagi yuklanayotganda (Suspense) — sarlavha + plitkalar + jadval. */
export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Sahifa yuklanmoqda">
      <Skeleton className="h-5 w-56" />
      <Skeleton className="mt-2 h-3 w-80 max-w-full" />
      <SkeletonTiles className="mt-4" />
      <SkeletonTable className="mt-4" />
    </div>
  );
}
