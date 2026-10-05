import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Avatar, Skeleton, cn, focusRing, type Tone, TONE_SOFT } from '../../ui';

export interface RankingItem {
  id: string;
  name: string;
  photoUrl?: string | null;
  /** Ism ostidagi qator (bo'linma, guruh ...). */
  subtitle?: ReactNode;
  /** O'ngdagi asosiy qiymat ("14 kun", "09:43"). */
  value: ReactNode;
  /** Qiymat ostidagi kichik izoh. */
  valueHint?: ReactNode;
  valueTone?: Tone;
  /** Ism yonidagi belgilar (streak va h.k.). */
  badges?: ReactNode;
  /** 0–100: qator ostidagi nisbiy chiziq. */
  bar?: number | null;
  to?: string;
  avatarStatus?: Tone | null;
}

export interface RankingListProps {
  items: RankingItem[];
  loading?: boolean;
  /** O'rin raqamini ko'rsatish (standart true). */
  numbered?: boolean;
  /** Birinchi uchtalikni ajratish. */
  highlightTop?: boolean;
  skeletonRows?: number;
  className?: string;
  ariaLabel?: string;
}

const VALUE_TEXT: Record<Tone, string> = {
  neutral: 'text-fg',
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

/** Reyting ro'yxati: o'rin, surat, ism + izoh, belgilar, o'ngda qiymat. */
export function RankingList({ items, loading, numbered = true, highlightTop = true, skeletonRows = 8, className, ariaLabel }: RankingListProps) {
  if (loading) {
    return (
      <ul className={cn('divide-y divide-border', className)} aria-busy="true">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <li key={i} className="flex items-center gap-3 py-3">
            <Skeleton className="h-9 w-9 rounded-full" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-5 w-12" />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ol className={cn('divide-y divide-border', className)} aria-label={ariaLabel}>
      {items.map((item, index) => {
        const rank = index + 1;
        const body = (
          <>
            {numbered && (
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums',
                  highlightTop && rank <= 3 ? TONE_SOFT[item.valueTone ?? 'primary'] : 'text-muted',
                )}
              >
                {rank}
              </span>
            )}
            <Avatar name={item.name} src={item.photoUrl ?? undefined} size="sm" status={item.avatarStatus ?? null} />
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="truncate text-sm font-medium text-fg group-hover:text-primary">{item.name}</span>
                {item.badges}
              </div>
              {item.subtitle && <div className="truncate text-xs text-muted">{item.subtitle}</div>}
              {item.bar !== undefined && item.bar !== null && (
                <div className="mt-1.5 h-1 w-full max-w-xs overflow-hidden rounded-full bg-surface-3">
                  <div
                    className={cn('h-full rounded-full transition-[width] duration-500', item.valueTone === 'danger' ? 'bg-danger' : item.valueTone === 'warning' ? 'bg-warning' : item.valueTone === 'success' ? 'bg-success' : 'bg-primary')}
                    style={{ width: `${Math.max(2, Math.min(100, item.bar))}%` }}
                  />
                </div>
              )}
            </div>
            <div className="shrink-0 text-right">
              <div className={cn('text-sm font-semibold tabular-nums', VALUE_TEXT[item.valueTone ?? 'neutral'])}>{item.value}</div>
              {item.valueHint && <div className="text-[11px] tabular-nums text-muted">{item.valueHint}</div>}
            </div>
          </>
        );
        return (
          <li key={item.id}>
            {item.to ? (
              <Link to={item.to} className={cn('group -mx-2 flex items-center gap-3 rounded-control px-2 py-2.5 transition-colors hover:bg-surface-2', focusRing)}>
                {body}
              </Link>
            ) : (
              <div className="flex items-center gap-3 py-2.5">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
