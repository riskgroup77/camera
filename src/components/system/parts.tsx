import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import {
  CodeText,
  ErrorState,
  MicroLabel,
  RAG_LETTER,
  RAG_LABEL,
  RAG_TEXT,
  RAG_SOLID,
  SkeletonText,
  TONE_SOLID,
  TONE_TEXT,
  cn,
  type Rag,
  type Tone,
} from '../../ui';
import type { LiveResource } from '../situation/useLiveResource';

/**
 * "Asboblar paneli" qismlari.
 *
 * Har ko'rsatkich — o'lchov: yorliq (bosh harf), monoshrift qiymat,
 * OCHIQ o'lchov birligi va — chegara haqiqatan mavjud bo'lsa — svetofor
 * hukmi (rang + harf). Chegarasi yo'q sanoqlar (ffmpeg jarayonlari,
 * shard soni) betaraf qoladi: ular ko'p yoki kam bo'lgani o'z-o'zidan
 * yaxshi yoki yomon emas.
 */

/** Millisekund → "14:03". Noma'lum bo'lsa null. */
export function clockTime(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return null;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}

/** "2026-09-20 14:03:22" yoki ISO → "20.09.2026 14:03". Tanib bo'lmasa o'zicha. */
export function formatServerTime(value: string | null | undefined, withSeconds = false): string | null {
  if (!value) return null;
  // Mintaqasi ko'rsatilgan vaqt (UTC "Z" yoki "+05:00") — Toshkentga o'giriladi;
  // ilgari UTC qatorlar 5 soat orqada ko'rinardi.
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(value)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      const parts = new Intl.DateTimeFormat('ru-RU', {
        timeZone: 'Asia/Tashkent', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: withSeconds ? '2-digit' : undefined, hour12: false,
      }).format(date);
      return parts.replace(',', '');
    }
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(value);
  if (!match) return value;
  const [, y, m, d, hh, mm, ss] = match;
  return `${d}.${m}.${y} ${hh}:${mm}${withSeconds && ss ? `:${ss}` : ''}`;
}

/** Svetofor belgisi: rang + HARF (rang yolg'iz qolmaydi). */
export function RagMark({ verdict, className }: { verdict: Rag; className?: string }) {
  if (verdict === 'yoq') return null;
  return (
    <span
      className={cn('inline-flex items-center gap-1', className)}
      title={RAG_LABEL[verdict]}
    >
      <span aria-hidden="true" className={cn('h-1.5 w-1.5 shrink-0', RAG_SOLID[verdict])} />
      <CodeText className={cn('text-[10px] font-bold', RAG_TEXT[verdict])}>{RAG_LETTER[verdict]}</CodeText>
      <span className="sr-only">{RAG_LABEL[verdict]}</span>
    </span>
  );
}

/**
 * Bitta o'lchov bloki: YORLIQ / qiymat + birlik / izoh.
 * `verdict` berilgandagina svetofor chiqadi.
 */
export function Metric({
  label,
  value,
  unit,
  hint,
  tone,
  verdict,
  title,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  verdict?: Rag;
  title?: string;
}) {
  return (
    <div className="min-w-0 border-s-2 border-border-strong bg-surface-2/60 px-2.5 py-1.5" title={title}>
      <MicroLabel className="block truncate">{label}</MicroLabel>
      <p className="mt-0.5 flex items-baseline gap-1.5">
        <CodeText
          className={cn(
            'text-[15px] font-semibold leading-tight',
            verdict && verdict !== 'yoq' ? RAG_TEXT[verdict] : tone ? TONE_TEXT[tone] : 'text-fg',
          )}
        >
          {value}
        </CodeText>
        {unit && <MicroLabel className="!text-subtle">{unit}</MicroLabel>}
        {verdict && <RagMark verdict={verdict} className="ms-auto" />}
      </p>
      {hint && <p className="mt-0.5 truncate text-[11px] leading-tight text-muted">{hint}</p>}
    </div>
  );
}

/** Holat qatori: rangli belgi + matn (rangga yolg'iz tayanmaydi). */
export function StatusLine({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 px-2.5 py-1.5 text-[13px] leading-5 text-fg">
      <span className={cn('mt-1.5 h-2 w-2 shrink-0', TONE_SOLID[tone])} aria-hidden="true" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** Tavsiya — faqat backend haqiqatan muammo topganda keladi. */
export function Recommendation({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="border-t border-border bg-surface-2/50 px-2.5 py-2 text-xs leading-relaxed text-muted">
      <MicroLabel className="me-2">Tavsiya</MicroLabel>
      {children}
    </p>
  );
}

/** Panel sarlavhasidagi "o'lchangan vaqt" tamg'asi. */
export function MeasuredAt({ resource }: { resource: { updatedAt: number | null; fetching?: boolean } }) {
  const at = clockTime(resource.updatedAt);
  return (
    <MicroLabel>
      {"O'lchandi"}: {at ?? '—'}
    </MicroLabel>
  );
}

/** Ustunli ruled qatorlar uchun ingichka ajratgich ro'yxati. */
export function RuledList({ children, className }: { children: ReactNode; className?: string }) {
  return <ul className={cn('divide-y divide-border', className)}>{children}</ul>;
}

/** Karta tanasi: yuklanish / xato / ma'lumot.
 *
 *  Fon yangilanishi xato bersa eski ma'lumot ekranda qoladi — avval bu
 *  jimgina bo'lardi va operator eskirgan raqamlarni jonli deb o'qirdi.
 *  Endi tepada ogohlantirish chiqadi: qachongi ma'lumot va nega yangilanmadi. */
export function ResourceBody<T>({ resource, children, lines = 4 }: { resource: LiveResource<T>; children: (data: T) => ReactNode; lines?: number }) {
  if (resource.data) {
    const at = clockTime(resource.updatedAt);
    return (
      <>
        {resource.error && (
          <p role="status" className="flex items-start gap-2 border-b border-warning/40 bg-warning-soft px-2.5 py-2 text-xs leading-relaxed text-fg">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
            <span className="min-w-0">
              Yangilanmadi — {at ?? 'eski'} ma'lumot. {resource.error}
            </span>
          </p>
        )}
        {children(resource.data)}
      </>
    );
  }
  if (resource.error) return <div className="p-3"><ErrorState message={resource.error} onRetry={resource.reload} /></div>;
  return <div className="p-3"><SkeletonText lines={lines} /></div>;
}
