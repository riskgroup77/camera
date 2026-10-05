import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn, TONE_TEXT, toneForRate, attendanceMeta, TONE_SOLID, type Tone } from '../../ui';

/** Devor paneli: sarlavha + ichki maydon. O'lchamlar `em` da — ildiz
 *  shrift o'lchami ekranga qarab (clamp) o'zgaradi. */
export function WallPanel({
  area,
  title,
  icon,
  aside,
  children,
  className,
}: {
  area: string;
  title: string;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      style={{ gridArea: area }}
      className={cn(
        'relative flex min-h-0 min-w-0 flex-col overflow-hidden border border-border bg-surface',
        className,
      )}
    >
      {/* Burchak qisqichlari — panel chegarasi uzoqdan ham "asbob"
          ramkasi bo'lib ko'rinadi (ekran 5 metrdan o'qiladi). */}
      <span aria-hidden="true" className="pointer-events-none absolute left-0 top-0 h-[0.7em] w-[0.7em] border-l-[0.14em] border-t-[0.14em] border-border-strong" />
      <span aria-hidden="true" className="pointer-events-none absolute right-0 top-0 h-[0.7em] w-[0.7em] border-r-[0.14em] border-t-[0.14em] border-border-strong" />
      <span aria-hidden="true" className="pointer-events-none absolute bottom-0 left-0 h-[0.7em] w-[0.7em] border-b-[0.14em] border-l-[0.14em] border-border-strong" />
      <span aria-hidden="true" className="pointer-events-none absolute bottom-0 right-0 h-[0.7em] w-[0.7em] border-b-[0.14em] border-r-[0.14em] border-border-strong" />

      <header className="flex shrink-0 items-center gap-[0.5em] border-b border-border bg-surface-2 px-[0.8em] py-[0.45em]">
        {icon && <span className="text-muted [&>svg]:h-[1em] [&>svg]:w-[1em]">{icon}</span>}
        <h2 className="intel-micro !text-[0.62em] !text-fg">{title}</h2>
        {aside && <div className="ms-auto flex items-center gap-[0.5em] text-[0.7em] text-muted">{aside}</div>}
      </header>
      <div className="relative flex min-h-0 flex-1 flex-col p-[0.8em]">{children}</div>
    </section>
  );
}

/** Devor uchun katta raqam: monoshrift, tabular, uzoqdan o'qiladi. */
export function WallReadout({
  value,
  label,
  tone,
  size = 2.6,
  className,
}: {
  value: ReactNode;
  label: string;
  tone?: string;
  /** Raqam balandligi `em` da. */
  size?: number;
  className?: string;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <div
        className={cn('intel-code font-semibold leading-[0.9] tracking-tight', tone ?? 'text-fg')}
        style={{ fontSize: `${size}em` }}
      >
        {value}
      </div>
      <div className="intel-micro mt-[0.45em] !text-[0.6em] truncate">{label}</div>
    </div>
  );
}

/** Ekran o'lchamiga moslashuvchi foiz halqasi (kenglik — `size` em). */
export function WallRing({
  value,
  size = 6,
  tone,
  label,
  sublabel,
}: {
  value: number | null | undefined;
  size?: number;
  tone?: Tone;
  label?: ReactNode;
  sublabel?: ReactNode;
}) {
  const has = value !== null && value !== undefined && !Number.isNaN(value);
  const pct = has ? Math.min(100, Math.max(0, value)) : 0;
  const t = tone ?? toneForRate(has ? value : null);
  const r = 42;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: `${size}em`, height: `${size}em` }}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r={r} fill="none" strokeWidth="9" className="stroke-surface-3" />
        {has && pct > 0 && (
          <circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c * (1 - pct / 100)}
            className={cn('transition-[stroke-dashoffset] duration-1000 ease-out', TONE_TEXT[t])}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="intel-code font-semibold text-fg" style={{ fontSize: `${size * 0.26}em` }}>
          {label ?? (has ? `${Math.round(pct)}%` : '—')}
        </span>
        {sublabel && (
          <span className="intel-micro mt-[0.4em]" style={{ fontSize: `${size * 0.1}em` }}>
            {sublabel}
          </span>
        )}
      </div>
    </div>
  );
}

/** Raqam silliq o'zgaradi (0.8 s). */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const [shown, setShown] = useState(value);
  // Ekranda hozir turgan son. Animatsiya tugamasdan yangi qiymat kelsa
  // (devor ekrani har 20 s da yangilanadi) keyingi animatsiya ana shu
  // sondan boshlanadi — ilgari nishondan boshlanib, raqam sakrardi.
  const shownRef = useRef(value);
  useEffect(() => {
    const from = shownRef.current;
    if (from === value) return;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / 800);
      const eased = 1 - Math.pow(1 - k, 3);
      const v = Math.round(from + (value - from) * eased);
      shownRef.current = v;
      setShown(v);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <span className={cn('intel-code', className)}>{shown.toLocaleString('ru-RU')}</span>;
}

const STATUS_RING: Record<Tone, string> = {
  neutral: 'ring-border-strong',
  primary: 'ring-primary',
  success: 'ring-success',
  warning: 'ring-warning',
  danger: 'ring-danger',
  info: 'ring-info',
};

/** Rasm yoki bosh harflar; holat rangidagi halqa bilan. */
export function WallFace({
  photoUrl,
  initials,
  status,
  className,
  dim,
}: {
  photoUrl: string | null;
  initials: string;
  status: string;
  className?: string;
  dim?: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const tone = attendanceMeta(status === 'malumot_yoq' ? 'nomalum' : status).tone;
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-[2px] bg-surface-2 ring-[0.18em] ring-offset-0',
        STATUS_RING[tone],
        dim && 'opacity-45 grayscale',
        className,
      )}
    >
      {photoUrl && !broken ? (
        <img src={photoUrl} alt="" loading="lazy" onError={() => setBroken(true)} className="h-full w-full object-cover" />
      ) : (
        <div className="intel-code flex h-full w-full items-center justify-center font-semibold text-muted" style={{ fontSize: '1.4em' }}>
          {initials}
        </div>
      )}
    </div>
  );
}

export function StatusPip({ status, className }: { status: string; className?: string }) {
  const tone = attendanceMeta(status === 'malumot_yoq' ? 'nomalum' : status).tone;
  return <span className={cn('inline-block h-[0.6em] w-[0.6em] shrink-0 rounded-[1px]', TONE_SOLID[tone], className)} />;
}
