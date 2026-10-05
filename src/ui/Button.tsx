import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import { Loader2, type LucideIcon } from 'lucide-react';
import { BUTTON_ICON_SIZE, buttonClasses, type ButtonSize, type ButtonVariant } from './buttonStyles';

interface CommonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Chapdagi ikonka (lucide). */
  icon?: LucideIcon;
  /** O'ngdagi ikonka (masalan ChevronDown, ExternalLink). */
  iconRight?: LucideIcon;
  fullWidth?: boolean;
}

export interface ButtonProps extends CommonProps, ButtonHTMLAttributes<HTMLButtonElement> {
  /** Yuklanish: spinner ko'rinadi, tugma bosilmaydi. */
  loading?: boolean;
}

function Content({
  icon: Icon,
  iconRight: IconRight,
  size = 'md',
  loading,
  children,
}: CommonProps & { loading?: boolean; children?: ReactNode }) {
  const iconSize = BUTTON_ICON_SIZE[size];
  return (
    <>
      {loading ? (
        <Loader2 size={iconSize} className="shrink-0 animate-spin" aria-hidden="true" />
      ) : (
        Icon && <Icon size={iconSize} className="shrink-0" aria-hidden="true" />
      )}
      {children}
      {IconRight && <IconRight size={iconSize} className="shrink-0 opacity-70" aria-hidden="true" />}
    </>
  );
}

/** Asosiy tugma. Variantlar: primary (sahifada bitta asosiy harakat),
 *  secondary (standart), ghost (ikkinchi darajali), danger, soft. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconRight, loading = false, fullWidth, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, fullWidth, className })}
      {...rest}
    >
      <Content icon={icon} iconRight={iconRight} size={size} loading={loading}>
        {children}
      </Content>
    </button>
  );
});

export interface ButtonLinkProps extends CommonProps, Omit<LinkProps, 'className'> {
  className?: string;
}

/** Tugma ko'rinishidagi ichki havola (react-router). Ctrl+bosish bilan
 *  yangi oynada ochiladi — oddiy tugmadan farqli. */
export function ButtonLink({ variant = 'secondary', size = 'md', icon, iconRight, fullWidth, className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={buttonClasses({ variant, size, fullWidth, className })} {...rest}>
      <Content icon={icon} iconRight={iconRight} size={size}>
        {children}
      </Content>
    </Link>
  );
}
