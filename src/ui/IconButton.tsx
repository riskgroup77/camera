import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Loader2, type LucideIcon } from 'lucide-react';
import { cn, focusRing } from './cn';

type Variant = 'ghost' | 'secondary' | 'primary' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const VARIANT: Record<Variant, string> = {
  ghost: 'border border-transparent text-muted hover:bg-surface-2 hover:text-fg',
  secondary: 'border border-border bg-surface text-muted hover:border-border-strong hover:bg-surface-2 hover:text-fg',
  primary: 'border border-primary bg-primary text-primary-fg hover:bg-primary/90',
  danger: 'border border-transparent text-danger hover:bg-danger-soft',
};

/** Tugma balandliklari Button bilan bir xil (28 / 32 / 34 px). */
const SIZE: Record<Size, { box: string; icon: number }> = {
  sm: { box: 'h-7 w-7', icon: 14 },
  md: { box: 'h-8 w-8', icon: 16 },
  lg: { box: 'h-[34px] w-[34px]', icon: 18 },
};

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: LucideIcon;
  /** Majburiy: ekran o'quvchi va tooltip uchun (aria-label + title). */
  label: string;
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** Burchakdagi hisoblagich (masalan o'qilmagan hodisalar). 0 — ko'rinmaydi. */
  badge?: number;
  /** Toggle tugma holati (aria-pressed). */
  pressed?: boolean;
}

/** Faqat ikonkali tugma. `label` doim beriladi — ekran o'quvchi uchun. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon: Icon, label, variant = 'ghost', size = 'md', loading, badge, pressed, className, disabled, type = 'button', title, ...rest },
  ref,
) {
  const { box, icon } = SIZE[size];
  const badgeText = badge && badge > 0 ? (badge > 99 ? '99+' : String(badge)) : null;
  return (
    <button
      ref={ref}
      type={type}
      aria-label={badgeText ? `${label} (${badgeText})` : label}
      title={title ?? label}
      aria-pressed={pressed}
      disabled={disabled || loading}
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center rounded-control transition-colors disabled:pointer-events-none disabled:opacity-50',
        focusRing,
        VARIANT[variant],
        pressed && 'bg-primary-soft text-primary hover:bg-primary-soft hover:text-primary',
        box,
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 size={icon} className="animate-spin" aria-hidden="true" /> : <Icon size={icon} aria-hidden="true" />}
      {badgeText && (
        <span className="intel-code absolute -right-1 -top-1 flex h-[15px] min-w-[15px] items-center justify-center rounded-[2px] border border-surface bg-danger px-0.5 text-[10px] font-bold leading-none text-danger-fg">
          {badgeText}
        </span>
      )}
    </button>
  );
});
