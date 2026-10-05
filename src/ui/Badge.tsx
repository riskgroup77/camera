import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from './cn';
import { TONE_SOFT, TONE_SOLID, TONE_BORDER, TONE_TEXT, type Tone } from './tones';
import {
  ATTENDANCE_STATUS,
  EVENT_STATUS,
  SEVERITY,
  type AttendanceStatus,
  type EventStatusKey,
  type SeverityKey,
} from './status';

export interface BadgeProps {
  tone?: Tone;
  variant?: 'soft' | 'solid' | 'outline';
  size?: 'sm' | 'md';
  /** Chapda rangli nuqta. */
  dot?: boolean;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
  title?: string;
}

const SOLID_TEXT: Record<Tone, string> = {
  neutral: 'bg-muted text-surface',
  primary: 'bg-primary text-primary-fg',
  success: 'bg-success text-success-fg',
  warning: 'bg-warning text-warning-fg',
  danger: 'bg-danger text-danger-fg',
  info: 'bg-info text-info-fg',
};

/** Kichik yorliq. Ma'nosi rang bilan emas, matn bilan ham beriladi. */
export function Badge({ tone = 'neutral', variant = 'soft', size = 'sm', dot, icon: Icon, children, className, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        // To'rtburchak nishon: monoshrift, ingichka chiziq — "tabletka" emas.
        'intel-code inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-[2px] border font-medium leading-none',
        size === 'sm' ? 'h-5 px-1.5 text-[11px]' : 'h-6 px-2 text-[12px]',
        variant === 'soft' && cn('border-border', TONE_SOFT[tone]),
        variant === 'solid' && cn('border-transparent', SOLID_TEXT[tone]),
        variant === 'outline' && cn('bg-transparent', TONE_BORDER[tone], TONE_TEXT[tone]),
        className,
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-[1px]', variant === 'solid' ? 'bg-current' : TONE_SOLID[tone])} aria-hidden="true" />}
      {Icon && <Icon size={size === 'sm' ? 11 : 12} className="shrink-0" aria-hidden="true" />}
      <span className="truncate">{children}</span>
    </span>
  );
}

type StatusBadgeProps =
  | { kind?: 'attendance'; status: AttendanceStatus | string | null | undefined }
  | { kind: 'event'; status: EventStatusKey }
  | { kind: 'severity'; status: SeverityKey };

/** Holat yorlig'i — davomat (standart), hodisa holati yoki jiddiylik.
 *  Rang va matn src/ui/status.ts'dan: barcha sahifalarda bir xil. */
export function StatusBadge(
  props: StatusBadgeProps & { size?: 'sm' | 'md'; className?: string; /** Holatdan keyin vaqt, masalan "08:12". */ time?: string | null },
) {
  let meta: { label: string; tone: Tone };
  if (props.kind === 'event') meta = EVENT_STATUS[props.status] ?? { label: props.status, tone: 'neutral' };
  else if (props.kind === 'severity') meta = SEVERITY[props.status] ?? { label: props.status, tone: 'neutral' };
  else meta = ATTENDANCE_STATUS[(props.status ?? 'nomalum') as AttendanceStatus] ?? ATTENDANCE_STATUS.nomalum;

  return (
    <Badge tone={meta.tone} dot size={props.size} className={props.className}>
      {meta.label}
      {props.time && <span className="ml-1 font-semibold opacity-80">{props.time}</span>}
    </Badge>
  );
}

/** Yolg'iz rangli nuqta (masalan jonli holat). `pulse` — jonli signal. */
export function StatusDot({ tone = 'neutral', pulse = false, className, label }: { tone?: Tone; pulse?: boolean; className?: string; label?: string }) {
  return (
    <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {pulse && <span className={cn('absolute inset-0 animate-ping rounded-[1px] opacity-60', TONE_SOLID[tone])} />}
      <span className={cn('relative inline-flex h-2 w-2 rounded-[1px]', TONE_SOLID[tone])} />
    </span>
  );
}
