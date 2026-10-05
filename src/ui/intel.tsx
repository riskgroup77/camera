import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * "Operatsiya markazi" uslubi — hisobotlar va kamera devori uchun.
 *
 * Maqsad: hujjat va jonli kuzatuv ekranlari rasmiy, xizmatga oid
 * ko'rinishga ega bo'lsin — qat'iy to'rt burchak, ingichka chiziq,
 * monoshrift raqamlar, har blokda hujjat kodi va vaqt tamg'asi.
 * Mavzu YORUG' qoladi: qog'ozga chiqadigan hujjat bilan ekrandagi
 * ko'rinish bir xil bo'lishi kerak.
 *
 * Bu yerda faqat KO'RINISH bor — hech qanday ma'lumot olish yoki
 * mantiq yo'q, shuning uchun har qanday sahifada ishlatilaveradi.
 */

/** Kichik bosh harfli yorliq: "QAMROV", "DAVR", "HOLAT". */
export function MicroLabel({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={cn('intel-micro', className)} title={title}>
      {children}
    </span>
  );
}

/** Monoshrift kod: hujjat raqami, kamera indeksi, koordinata.
 *  `title` — qisqartirilgan kodning to'liq shakli (sichqoncha ostida). */
export function CodeText({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={cn('intel-code', className)} title={title}>
      {children}
    </span>
  );
}

/** Yorliq + qiymat juftligi (yuqoridagi ma'lumot satri uchun). */
export function Readout({
  label,
  value,
  title,
  className,
}: {
  label: string;
  value: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-0.5', className)} title={title}>
      <MicroLabel>{label}</MicroLabel>
      <span className="intel-code truncate text-[13px] font-semibold text-fg">{value}</span>
    </div>
  );
}

export type IntelStatus = 'ok' | 'warn' | 'alert' | 'idle';

const DOT_TONE: Record<IntelStatus, string> = {
  ok: 'bg-success',
  warn: 'bg-warning',
  alert: 'bg-danger',
  idle: 'bg-subtle',
};

/** Holat chirog'i — matn bilan birga (faqat rangga tayanmaydi). */
export function StatusLamp({
  status,
  label,
  pulse = false,
  className,
}: {
  status: IntelStatus;
  label: string;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        aria-hidden="true"
        className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT_TONE[status], pulse && 'intel-pulse')}
      />
      <MicroLabel>{label}</MicroLabel>
    </span>
  );
}

/**
 * Asosiy blok: burchaklarida qisqich belgilari, tepasida sarlavha
 * chizig'i va o'ng tomonida kod.
 */
export function IntelPanel({
  title,
  code,
  right,
  children,
  className,
  bodyClassName,
  brackets = true,
}: {
  title?: ReactNode;
  code?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  brackets?: boolean;
}) {
  return (
    <section className={cn('intel-panel', brackets && 'intel-brackets', className)}>
      {(title || code || right) && (
        <header className="flex items-center gap-3 border-b border-border bg-surface-2 px-3 py-2">
          {title && <h2 className="intel-micro !text-fg">{title}</h2>}
          <span className="ms-auto flex items-center gap-3">
            {right}
            {code && <CodeText className="text-subtle">{code}</CodeText>}
          </span>
        </header>
      )}
      <div className={cn('min-w-0', bodyClassName)}>{children}</div>
    </section>
  );
}

/**
 * Hujjat sarlavhasi — rasmiy blank ko'rinishi: tashkilot, hujjat nomi,
 * o'ng tomonda ro'yxat raqami va tuzilgan vaqti, ostida ma'lumot satri.
 * Qog'ozga ham chiqadi (print-hide QO'YILMAGAN).
 */
export function DocumentHeader({
  org,
  title,
  reference,
  generatedAt,
  readouts,
  className,
}: {
  org: string;
  title: string;
  reference: string;
  generatedAt?: string;
  readouts?: { label: string; value: ReactNode; title?: string }[];
  className?: string;
}) {
  return (
    <header className={cn('intel-doc-head', className)}>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2 border-b border-border-strong px-4 py-3">
        <div className="min-w-0 flex-1">
          <MicroLabel>{org}</MicroLabel>
          <h1 className="mt-0.5 truncate text-[17px] font-semibold tracking-tight text-fg">{title}</h1>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
          <CodeText className="text-[12px] font-semibold text-fg">{reference}</CodeText>
          {generatedAt && <MicroLabel>Tuzildi: {generatedAt}</MicroLabel>}
        </div>
      </div>
      {readouts && readouts.length > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-border px-4 py-3 sm:grid-cols-3 lg:grid-cols-4">
          {readouts.map((item) => (
            <Readout key={item.label} label={item.label} value={item.value} title={item.title} />
          ))}
        </div>
      )}
    </header>
  );
}

/** Hujjatning pastki qismi: kim tuzdi, qachon, imzo joyi. */
export function DocumentFooter({ note, className }: { note?: ReactNode; className?: string }) {
  return (
    <footer className={cn('border-t border-border px-4 py-3', className)}>
      {note && <p className="intel-micro !normal-case !tracking-normal !text-muted">{note}</p>}
    </footer>
  );
}
