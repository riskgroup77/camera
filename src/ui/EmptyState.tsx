import { isValidElement, type ReactNode } from 'react';
import { Inbox, type LucideIcon } from 'lucide-react';
import { cn } from './cn';

export interface EmptyStateProps {
  /** Lucide ikonka komponenti yoki tayyor element. */
  icon?: LucideIcon | ReactNode;
  title: ReactNode;
  /** Nega bo'sh va nima qilish mumkin. */
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  /** Illyustratsiya ohangi (standart: neytral). */
  tone?: 'neutral' | 'primary' | 'success' | 'warning' | 'info';
  /** Uzuq chegara (standart). Karta ichida `false`. */
  bordered?: boolean;
  className?: string;
}

/** "Ma'lumot yo'q" holati: sabab va keyingi qadam bilan. */
export function EmptyState({ icon = Inbox, title, description, action, compact = false, bordered = true, tone = 'neutral', className }: EmptyStateProps) {
  let iconNode: ReactNode;
  if (isValidElement(icon)) iconNode = icon;
  else if (typeof icon === 'function' || (typeof icon === 'object' && icon !== null && '$$typeof' in icon)) {
    const Icon = icon as LucideIcon;
    iconNode = <Icon size={compact ? 18 : 24} strokeWidth={1.8} aria-hidden="true" />;
  } else iconNode = icon;

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        bordered && 'rounded-card border border-dashed border-border-strong bg-surface-2/60',
        compact ? 'px-4 py-5' : 'px-6 py-10 sm:py-12',
        className,
      )}
    >
      {compact ? (
        <div className={cn('mb-2.5 flex h-8 w-8 items-center justify-center rounded-[2px] border border-border', ILLU_TONE[tone].chip)}>{iconNode}</div>
      ) : (
        <EmptyIllustration tone={tone}>{iconNode}</EmptyIllustration>
      )}
      {/* "Ma'lumot yo'q" — bu ham o'lchov natijasi: bosh harfli qayd. */}
      <p className={cn('intel-micro intel-micro-wrap !text-fg', !compact && '!text-[12px]')}>{title}</p>
      {description && <p className="mt-1.5 max-w-md text-[12px] leading-relaxed text-muted">{description}</p>}
      {action && <div className="mt-3 flex flex-wrap justify-center gap-1.5">{action}</div>}
    </div>
  );
}

const ILLU_TONE = {
  neutral: { chip: 'bg-surface-2 text-muted', accent: 'text-subtle' },
  primary: { chip: 'bg-primary-soft text-primary', accent: 'text-primary' },
  success: { chip: 'bg-success-soft text-success', accent: 'text-success' },
  warning: { chip: 'bg-warning-soft text-warning', accent: 'text-warning' },
  info: { chip: 'bg-info-soft text-info', accent: 'text-info' },
} as const;

/** Bo'sh qamrov belgisi: o'lchov to'ri, nishon qisqichlari va o'rtada
 *  ikonka. Bezak emas — "bu yerda qaraldi, hech narsa topilmadi" degani.
 *  Ekran o'quvchilardan yashirin. */
function EmptyIllustration({ tone, children }: { tone: keyof typeof ILLU_TONE; children: ReactNode }) {
  const t = ILLU_TONE[tone];
  return (
    <div className="relative mb-3 h-[76px] w-[112px]" aria-hidden="true">
      <div className="intel-grid absolute inset-0 opacity-60" />
      <div className="intel-brackets absolute inset-0 border border-border" />
      <div className={cn('absolute left-1/2 top-1/2 flex h-10 w-10 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-[2px] border border-border', t.chip)}>
        {children}
      </div>
    </div>
  );
}
