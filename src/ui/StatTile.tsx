import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from 'lucide-react';
import { cn, focusRing } from './cn';
import { CountUp } from './CountUp';
import { Sparkline } from './Sparkline';
import { ProgressBar } from './Progress';
import { Skeleton } from './Skeleton';
import { TONE_TEXT, type Tone } from './tones';
import { RAG_LABEL, RAG_SOLID, type Rag } from './rag';

/** `.intel-micro` rangni oddiy CSS'da beradi — uni yengish uchun `!`.
 *  Sinf nomlari SATR sifatida yozilgan: Tailwind faylni shunday skanerlaydi. */
const RAG_MICRO: Record<Rag, string> = {
  yashil: '!text-success',
  sariq: '!text-warning',
  qizil: '!text-danger',
  yoq: '!text-subtle',
};

export interface StatDelta {
  /** Oldingi davrga nisbatan o'zgarish (masalan +3.2 yoki -12). */
  value: number;
  /** Ko'rsatiladigan matn (standart: "+3,2"). */
  display?: string;
  /** Qaysi yo'nalish yaxshi: 'up' (davomat), 'down' (kechikish), 'none' — neytral. */
  better?: 'up' | 'down' | 'none';
}

export interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  /** Qiymat yonidagi birlik ("ta", "%"). */
  unit?: ReactNode;
  /** Pastdagi izoh ("1 240 tadan"). */
  hint?: ReactNode;
  icon?: LucideIcon;
  /** Ikonka va progress rangi. */
  tone?: Tone;
  delta?: StatDelta | null;
  /** 0–100 — ostida chiziqli progress. */
  progress?: number | null;
  loading?: boolean;
  /** Bosiladigan plitka: ichki havola. */
  to?: string;
  onClick?: () => void;
  size?: 'md' | 'lg';
  /** Kichik trend chizig'i (masalan oxirgi 14 kun), eskisi birinchi. */
  trend?: ReadonlyArray<number | null> | null;
  /** Raqamni silliq sanab ko'rsatish (standart: yoqilgan). */
  animate?: boolean;
  /** Svetofor: chiroq + hukm so'zi ("Chora kerak") o'lchov ostida. */
  rag?: Rag | null;
  className?: string;
}

function deltaTone(delta: StatDelta): Tone {
  if (delta.value === 0 || !delta.better || delta.better === 'none') return 'neutral';
  const improved = delta.better === 'up' ? delta.value > 0 : delta.value < 0;
  return improved ? 'success' : 'danger';
}

/**
 * O'lchov bloki: bosh harfli mikro-yorliq, katta monoshrift qiymat va
 * birlik, ixtiyoriy svetofor chirog'i + hukm so'zi, o'zgarish va izoh.
 * To'rtburchak, ingichka chiziqli, soyasiz.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  icon: Icon,
  tone = 'neutral',
  delta,
  progress,
  loading,
  to,
  onClick,
  size = 'md',
  trend,
  animate = true,
  rag,
  className,
}: StatTileProps) {
  const DeltaIcon = delta ? (delta.value === 0 ? Minus : delta.value > 0 ? ArrowUpRight : ArrowDownRight) : null;
  const dTone = delta ? deltaTone(delta) : 'neutral';

  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="intel-micro intel-micro-wrap">{label}</span>
        {Icon && <Icon size={14} aria-hidden="true" className={cn('mt-px shrink-0', TONE_TEXT[tone])} />}
      </div>

      {loading ? (
        <Skeleton className={cn('mt-2', size === 'lg' ? 'h-8 w-28' : 'h-7 w-20')} />
      ) : (
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5">
          <span
            className={cn(
              'intel-code font-semibold leading-none tracking-tight text-fg',
              size === 'lg' ? 'text-[30px]' : 'text-[24px]',
            )}
          >
            {animate ? <CountUp value={value} /> : value}
          </span>
          {unit && <span className="intel-code text-[13px] font-medium text-muted">{unit}</span>}
        </div>
      )}

      {/* Svetofor: chiroq YOLG'IZ emas — yonida hukm so'zi turadi. */}
      {rag && !loading && (
        <div className="mt-2 flex items-center gap-1.5 border-t border-border pt-1.5">
          <span className={cn('h-2 w-2 shrink-0 rounded-[1px]', RAG_SOLID[rag])} aria-hidden="true" />
          <span className={cn('intel-micro', RAG_MICRO[rag])}>{RAG_LABEL[rag]}</span>
        </div>
      )}

      {(delta || hint) && !loading && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
          {delta && DeltaIcon && (
            <span className={cn('intel-code inline-flex items-center gap-0.5 text-[12px] font-semibold', TONE_TEXT[dTone])}>
              <DeltaIcon size={12} aria-hidden="true" />
              {delta.display ?? `${delta.value > 0 ? '+' : ''}${delta.value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}`}
            </span>
          )}
          {hint && <span className="min-w-0 text-[12px] leading-4 text-muted">{hint}</span>}
        </div>
      )}

      {trend && !loading && <Sparkline values={trend} tone={tone === 'neutral' ? 'primary' : tone} height={24} className="mt-2.5" />}
      {progress !== undefined && progress !== null && !loading && (
        <ProgressBar value={progress} tone={tone === 'neutral' ? 'auto' : tone} size="xs" className="mt-2.5" />
      )}
    </>
  );

  const classes = cn(
    'flex min-w-0 flex-col rounded-card border border-border bg-surface p-3 text-left',
    (to || onClick) && cn('transition-colors hover:border-border-strong hover:bg-primary/[0.03]', focusRing),
    className,
  );

  if (to) {
    return (
      <Link to={to} className={classes}>
        {content}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={classes}>
        {content}
      </button>
    );
  }
  return <div className={classes}>{content}</div>;
}
