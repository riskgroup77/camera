import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn, focusRing } from './cn';
import { initials } from './text';
import { attendanceMeta, type AttendanceStatus } from './status';
import { TONE_SOFT, TONE_SOLID } from './tones';

export interface PersonCardProps {
  name: string;
  photoUrl?: string | null;
  /** Guruh, kafedra yoki lavozim. */
  subtitle?: ReactNode;
  status?: AttendanceStatus | string | null;
  /** Kelgan vaqti ("08:12") yoki boshqa qisqa vaqt. */
  time?: string | null;
  /** Qo'shimcha qator (masalan "3 dars"). */
  meta?: ReactNode;
  /** Ichki havola (masalan /shaxs/123). */
  to?: string;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}

/** "Yuzlar setkasi" elementi: surat, ism, holat va vaqt. Holat rangi
 *  pastki chiziqda va yorliqda — faqat rangga tayanmaydi. */
export function PersonCard({ name, photoUrl, subtitle, status, time, meta, to, onClick, selected, className }: PersonCardProps) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [photoUrl]);
  const statusMeta = attendanceMeta(status ?? undefined);
  const showPhoto = photoUrl && !failed;

  const body = (
    <>
      <div className={cn('relative aspect-[4/5] w-full overflow-hidden bg-surface-2', !showPhoto && TONE_SOFT[statusMeta.tone])}>
        {showPhoto ? (
          <img
            src={photoUrl}
            alt=""
            loading="lazy"
            onError={() => setFailed(true)}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center text-3xl font-semibold opacity-80" aria-hidden="true">
            {initials(name)}
          </span>
        )}
        {status && (
          /* Holat yorlig'i — to'rtburchak qayd: rang + so'z birga. */
          <span className="intel-micro absolute left-1 top-1 inline-flex items-center gap-1 border border-border bg-surface/95 px-1 py-0.5 !text-fg">
            <span className={cn('h-1.5 w-1.5 rounded-[1px]', TONE_SOLID[statusMeta.tone])} aria-hidden="true" />
            {statusMeta.label}
          </span>
        )}
        <span className={cn('absolute inset-x-0 bottom-0 h-[3px]', status ? TONE_SOLID[statusMeta.tone] : 'bg-transparent')} aria-hidden="true" />
      </div>
      <div className="flex min-h-[3.75rem] flex-col gap-0.5 border-t border-border p-2">
        {/* Odam ismi — proza: sans shriftda qoladi. */}
        <p className="line-clamp-2 text-[12px] font-semibold leading-snug text-fg" title={name}>
          {name}
        </p>
        <div className="mt-auto flex items-center justify-between gap-2">
          <span className="intel-micro min-w-0 truncate">{subtitle}</span>
          {time && <span className="intel-code shrink-0 text-[12px] font-semibold text-fg">{time}</span>}
        </div>
        {meta && <div className="intel-micro">{meta}</div>}
      </div>
    </>
  );

  const classes = cn(
    'group flex flex-col overflow-hidden rounded-card border bg-surface text-left transition-colors',
    selected ? 'border-primary shadow-[inset_0_0_0_1px_rgb(var(--c-primary))]' : 'border-border',
    (to || onClick) && cn('hover:border-border-strong', focusRing),
    className,
  );
  const label = `${name}${status ? `, ${statusMeta.label}` : ''}${time ? `, ${time}` : ''}`;

  if (to) {
    return (
      <Link to={to} className={classes} aria-label={label}>
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={classes} aria-label={label} aria-pressed={selected}>
        {body}
      </button>
    );
  }
  return (
    <div className={classes} aria-label={label} role="group">
      {body}
    </div>
  );
}

/** PersonCard'lar uchun moslashuvchan setka: telefonda 2 ta, katta ekranda ko'p. */
export function PersonGrid({ children, minItemWidth = 140, className }: { children: ReactNode; minItemWidth?: number; className?: string }) {
  return (
    <div
      className={cn('grid gap-2', className)}
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, ${minItemWidth}px), 1fr))` }}
    >
      {children}
    </div>
  );
}
