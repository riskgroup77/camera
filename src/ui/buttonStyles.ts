import { cn, focusRing } from './cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft';
export type ButtonSize = 'sm' | 'md' | 'lg';

/** Harakatlar aniq ko'rinadi: asosiy amal chuqur rangda, qolganlari yorug' sirtda. */
const VARIANT: Record<ButtonVariant, string> = {
  primary: 'border border-primary bg-primary text-primary-fg shadow-[0_10px_18px_-10px_rgb(45_83_222/0.7)] hover:-translate-y-px hover:bg-primary/90 active:translate-y-0',
  secondary: 'border border-white bg-surface text-fg shadow-[0_8px_16px_-14px_rgb(42_72_130/0.35)] hover:-translate-y-px hover:border-primary/20 hover:bg-primary-soft',
  ghost: 'border border-transparent text-muted hover:bg-primary-soft hover:text-primary',
  danger: 'border border-danger bg-danger text-danger-fg shadow-[0_10px_18px_-10px_rgb(221_75_91/0.6)] hover:-translate-y-px hover:bg-danger/90 active:translate-y-0',
  soft: 'border border-primary/10 bg-primary-soft text-primary hover:-translate-y-px hover:border-primary/25 hover:bg-primary/15',
};

const SIZE: Record<ButtonSize, string> = {
  sm: 'h-7 gap-1.5 px-2.5 text-[12px]',
  md: 'h-8 gap-1.5 px-3 text-[13px]',
  lg: 'h-[34px] gap-2 px-4 text-[14px]',
};

export const BUTTON_ICON_SIZE: Record<ButtonSize, number> = { sm: 13, md: 14, lg: 16 };

/** Tugma ko'rinishini boshqa element (masalan <a>, <label>) uchun olish. */
export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  fullWidth = false,
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  className?: string;
} = {}): string {
  return cn(
    'inline-flex select-none items-center justify-center whitespace-nowrap rounded-control font-semibold transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50',
    focusRing,
    VARIANT[variant],
    SIZE[size],
    fullWidth && 'w-full',
    className,
  );
}
