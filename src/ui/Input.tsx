import { cloneElement, forwardRef, isValidElement, useId, type InputHTMLAttributes, type ReactElement, type ReactNode, type TextareaHTMLAttributes } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn, controlBase, controlSizes, type ControlSize } from './cn';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  size?: ControlSize;
  /** Chapdagi ikonka. */
  icon?: LucideIcon;
  /** O'ngdagi element (masalan parolni ko'rsatish tugmasi). */
  trailing?: ReactNode;
  invalid?: boolean;
}

/** Matn maydoni. Yorliq va xato uchun `Field` bilan o'rang. */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { size = 'md', icon: Icon, trailing, invalid, className, ...rest },
  ref,
) {
  return (
    <div className={cn('relative w-full', className)}>
      {Icon && (
        <Icon size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
      )}
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          'intel-code',
          controlBase,
          controlSizes[size],
          Icon && 'pl-8',
          trailing ? 'pr-9' : undefined,
          invalid && 'border-danger focus:border-danger focus:ring-danger/20',
        )}
        {...rest}
      />
      {trailing && <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center">{trailing}</div>}
    </div>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(function Textarea(
  { invalid, className, rows = 3, ...rest },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid || undefined}
      // Erkin matn — odam yozadigan gap: sans shriftda qoladi.
      className={cn(controlBase, 'min-h-[4.5rem] px-2.5 py-1.5 text-[13px]', invalid && 'border-danger focus:border-danger focus:ring-danger/20', className)}
      {...rest}
    />
  );
});

export interface FieldProps {
  label: ReactNode;
  /** Bitta boshqaruv elementi (Input, Select, Textarea...) — id va aria avtomatik ulanadi. */
  children: ReactElement<{ id?: string; 'aria-describedby'?: string; invalid?: boolean }>;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
}

/** Yorliq + boshqaruv + izoh/xato. Xato ekran o'quvchiga ham o'qiladi. */
export function Field({ label, children, hint, error, required, className }: FieldProps) {
  const autoId = useId();
  const childId = (isValidElement(children) && children.props.id) || autoId;
  const hintId = `${childId}-hint`;
  const describedBy = error || hint ? hintId : undefined;
  const control = isValidElement(children)
    ? cloneElement(children, { id: childId, 'aria-describedby': describedBy, ...(error ? { invalid: true } : {}) })
    : children;

  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      {/* Maydon nomi — bosh harfli mikro-yorliq (blankdagi katak nomi). */}
      <label htmlFor={childId} className="intel-micro intel-micro-wrap !text-fg">
        {label}
        {required && <span className="ml-0.5 !text-danger" aria-hidden="true">*</span>}
      </label>
      {control}
      {(error || hint) && (
        <p id={hintId} className={cn('text-[12px] leading-4', error ? 'font-medium text-danger' : 'text-muted')} role={error ? 'alert' : undefined}>
          {error || hint}
        </p>
      )}
    </div>
  );
}
