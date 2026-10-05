import type { InputHTMLAttributes, ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, XCircle, type LucideIcon } from 'lucide-react';
import { IconButton, cn, focusRing } from '../../ui';

/* Sozlamalar sahifalari (kameralar, AI, bildirishnomalar, integratsiyalar,
 * foydalanuvchilar, maxfiylik) va ochiq ro'yxatdan o'tish uchun umumiy kichik
 * bo'laklar. src/ui'da hali yo'q — kerak bo'lsa u yerga ko'chiriladi. */

/* ── Sahifalash (DataTable footer uchun) ── */

export interface TablePagerProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onChange: (page: number) => void;
  className?: string;
}

/** "1–10 / 57 ta" + oldingi/keyingi. Bitta sahifa bo'lsa — faqat jami. */
export function TablePager({ page, totalPages, total, pageSize, onChange, className }: TablePagerProps) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3 text-[13px]', className)}>
      <span className="tabular-nums text-muted">
        {totalPages > 1 ? `${from}–${to} / ${total.toLocaleString('ru-RU')} ta` : `Jami: ${total.toLocaleString('ru-RU')} ta`}
      </span>
      {totalPages > 1 && (
        <div className="flex items-center gap-1">
          <IconButton icon={ChevronLeft} label="Oldingi sahifa" size="sm" variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)} />
          <span className="min-w-[4.5rem] text-center font-medium tabular-nums text-fg">
            {page} / {totalPages}
          </span>
          <IconButton icon={ChevronRight} label="Keyingi sahifa" size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => onChange(page + 1)} />
        </div>
      )}
    </div>
  );
}

/** DataTable `footer` uchun: bitta sahifa va bo'sh ro'yxatda hech narsa chizmaydi. */
// oxlint-disable-next-line react/only-export-components
export function pagerFooter(props: TablePagerProps): ReactNode {
  if (props.totalPages <= 1) return undefined;
  return <TablePager {...props} />;
}

/* ── Belgilash katakchasi ── */

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'children'> {
  label?: ReactNode;
  description?: ReactNode;
}

/** Native checkbox (klaviatura/ekran o'quvchi bilan to'liq) + yorliq va izoh. */
export function Checkbox({ label, description, className, disabled, ...rest }: CheckboxProps) {
  const box = (
    <input
      type="checkbox"
      disabled={disabled}
      className={cn('mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-border accent-primary disabled:cursor-not-allowed', focusRing, !label && className)}
      {...rest}
    />
  );
  if (!label) return box;
  return (
    <label className={cn('flex cursor-pointer items-start gap-2.5 text-sm text-fg', disabled && 'cursor-not-allowed opacity-60', className)}>
      {box}
      <span className="min-w-0">
        <span className="block font-medium leading-5">{label}</span>
        {description && <span className="mt-0.5 block text-[13px] leading-5 text-muted">{description}</span>}
      </span>
    </label>
  );
}

/* ── Kalit (on/off) ── */

export function Switch({
  checked,
  onChange,
  label,
  disabled,
  className,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  /** Ekran o'quvchi uchun (ko'rinadigan yorliq bo'lmasa ham majburiy). */
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-primary' : 'bg-surface-3 ring-1 ring-inset ring-border',
        focusRing,
        className,
      )}
    >
      <span className={cn('inline-block h-4 w-4 rounded-full bg-surface shadow-sm transition-transform', checked ? 'translate-x-[18px]' : 'translate-x-0.5')} />
    </button>
  );
}

/* ── Izoh / ogohlantirish bloki ── */

type NoticeTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral';

const NOTICE: Record<NoticeTone, { box: string; icon: LucideIcon; iconClass: string }> = {
  info: { box: 'border-info/25 bg-info-soft', icon: Info, iconClass: 'text-info' },
  success: { box: 'border-success/25 bg-success-soft', icon: CheckCircle2, iconClass: 'text-success' },
  warning: { box: 'border-warning/30 bg-warning-soft', icon: AlertTriangle, iconClass: 'text-warning' },
  danger: { box: 'border-danger/25 bg-danger-soft', icon: XCircle, iconClass: 'text-danger' },
  neutral: { box: 'border-border bg-surface-2', icon: Info, iconClass: 'text-muted' },
};

/** Forma/karta ichidagi izoh: nima bo'ldi yoki nimaga e'tibor berish kerak.
 *  `tone="danger"` — forma xatosi (role=alert). */
export function Notice({
  tone = 'info',
  title,
  children,
  icon,
  action,
  className,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  icon?: LucideIcon | null;
  action?: ReactNode;
  className?: string;
}) {
  const meta = NOTICE[tone];
  const Icon = icon === null ? null : (icon ?? meta.icon);
  return (
    <div
      role={tone === 'danger' ? 'alert' : undefined}
      className={cn('flex items-start gap-2.5 rounded-control border px-3 py-2.5 text-[13px] leading-5 text-fg', meta.box, className)}
    >
      {Icon && <Icon size={16} className={cn('mt-0.5 shrink-0', meta.iconClass)} aria-hidden="true" />}
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn(title ? 'mt-0.5' : undefined, 'text-fg/85')}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Teng kenglikdagi ikki-uch variantli tanlov (radio) — formalarda
 *  (masalan "JSHSHIR / Pasport", "Talaba / Xodim"). To'liq kenglikda. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  size = 'md',
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: ReactNode; icon?: LucideIcon }[];
  ariaLabel: string;
  size?: 'md' | 'lg';
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn('grid gap-1 rounded-control border border-border bg-surface-2 p-1', className)}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map((option) => {
        const active = option.value === value;
        const Icon = option.icon;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex min-w-0 items-center justify-center gap-1.5 rounded-[6px] px-3 font-medium transition-colors',
              size === 'lg' ? 'h-10 text-sm' : 'h-8 text-[13px]',
              active ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
              focusRing,
            )}
          >
            {Icon && <Icon size={16} aria-hidden="true" className={active ? 'text-primary' : undefined} />}
            <span className="truncate">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Tanlash tugmalari guruhi (radio kartalar) — masalan, rol yoki kanal tanlash. */
export function ChoiceCards<T extends string>({
  value,
  onChange,
  options,
  name,
  columns = 2,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: ReactNode; description?: ReactNode; icon?: LucideIcon; disabled?: boolean }[];
  name: string;
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  const cols = columns === 1 ? 'grid-cols-1' : columns === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1 sm:grid-cols-3';
  return (
    <div role="radiogroup" className={cn('grid gap-2', cols, className)}>
      {options.map((option) => {
        const active = option.value === value;
        const Icon = option.icon;
        return (
          <label
            key={option.value}
            className={cn(
              'flex cursor-pointer items-start gap-2.5 rounded-control border px-3 py-2.5 transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-primary/40',
              active ? 'border-primary bg-primary-soft' : 'border-border bg-surface hover:border-border-strong',
              option.disabled && 'cursor-not-allowed opacity-50',
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={active}
              disabled={option.disabled}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {Icon && <Icon size={16} aria-hidden="true" className={cn('mt-0.5 shrink-0', active ? 'text-primary' : 'text-muted')} />}
            <span className="min-w-0">
              <span className={cn('block text-sm font-medium', active ? 'text-primary' : 'text-fg')}>{option.label}</span>
              {option.description && <span className="mt-0.5 block text-xs text-muted">{option.description}</span>}
            </span>
          </label>
        );
      })}
    </div>
  );
}
