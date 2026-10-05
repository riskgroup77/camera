import type { HTMLAttributes, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from './cn';

type Padding = 'none' | 'sm' | 'md' | 'lg';

/** Panel ichki bo'shlig'i: 12–16px. Ish asbobi zich bo'ladi. */
const PADDING: Record<Padding, string> = {
  none: '',
  sm: 'p-2.5',
  md: 'p-3',
  lg: 'p-4',
};

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: Padding;
  /** Bosiladigan karta: hover va fokus holati. (onClick bilan birga.) */
  interactive?: boolean;
  as?: 'div' | 'section' | 'article';
}

/** Barcha sahifadagi yagona premium sirt: keng qirra, yengil nur va tabiiy soya. */
export function Card({ padding = 'md', interactive = false, as: Tag = 'div', className, children, ...rest }: CardProps) {
  return (
    <Tag
      className={cn(
        'rounded-card border border-white/90 bg-surface shadow-card',
        PADDING[padding],
        interactive &&
          'cursor-pointer transition duration-200 hover:-translate-y-0.5 hover:border-primary/20 hover:shadow-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35',
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export interface CardHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  /** O'ng tomondagi tugmalar/havolalar. */
  actions?: ReactNode;
  className?: string;
  /** Sarlavha darajasi (sahifa tuzilishi uchun). Standart h3. */
  level?: 2 | 3 | 4;
}

/** Karta sarlavhasi: oddiy nom, aniq ikkilamchi izoh va tabiiy masofa. */
export function CardHeader({ title, subtitle, icon: Icon, actions, className, level = 3 }: CardHeaderProps) {
  const Heading = `h${level}` as 'h2' | 'h3' | 'h4';
  return (
    <div className={cn('mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5', className)}>
      <div className="flex min-w-0 items-start gap-2">
        {Icon && <Icon size={14} aria-hidden="true" className="mt-px shrink-0 text-muted" />}
        <div className="min-w-0">
          <Heading className="text-[15px] font-bold tracking-[-0.02em] text-fg">{title}</Heading>
          {subtitle && <p className="mt-0.5 text-[12px] leading-4 text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-1.5">{actions}</div>}
    </div>
  );
}
