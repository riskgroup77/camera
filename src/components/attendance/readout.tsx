import type { ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import { CodeText, MicroLabel, cn } from '../../ui';
import { RAG_LABEL, RAG_SOLID, RAG_TEXT, RATE_RAG, rag, type Rag, type RagThresholds } from '../../ui/rag';
import { RagChip, boardRag, type BoardItem } from '../hisobot/board';

/**
 * Davomat ekranlari uchun umumiy "asbob" bo'laklari.
 *
 * Bu yerda faqat KO'RINISH bor. Qoida bitta: foiz — svetofor bilan,
 * xom son — svetoforsiz. "12 ta kechikish" yaxshimi yoki yomonmi,
 * bo'linma kattaligini bilmasdan aytib bo'lmaydi, rang esa aniq hukm.
 */

const TONE_ORDER: Record<Rag, number> = { qizil: 0, sariq: 1, yashil: 2, yoq: 3 };

/** Yomoni birinchi: rahbar ekranning yuqorisidan chora kerak bo'lgan joyni
 *  topadi, pastga qarab tinchlanadi. O'lchanmaganlar oxirida — ularga
 *  hukm chiqarilmagan, shuning uchun "eng yaxshi" ham, "eng yomon" ham emas. */
export function worstFirst(items: BoardItem[], thresholds: RagThresholds = RATE_RAG): BoardItem[] {
  return [...items].sort((a, b) => {
    const byTone = TONE_ORDER[boardRag(a, thresholds)] - TONE_ORDER[boardRag(b, thresholds)];
    if (byTone !== 0) return byTone;
    const av = a.value ?? Infinity;
    const bv = b.value ?? Infinity;
    if (av !== bv) return av - bv;
    // Xizmat kodlari olib tashlandi — teng qiymatlar nom bo'yicha turadi,
    // shunda tartib har renderda bir xil chiqadi.
    return a.name.localeCompare(b.name);
  });
}

export interface KpiItem {
  label: string;
  /** Katta raqam. Tayyor matn ham bo'ladi ("08:25", "2 / 12"). */
  value: ReactNode;
  /** Birlik yozuvi: "kun", "ta", "%". */
  unit?: string;
  /**
   * Svetofor uchun foiz. `undefined` — bu ko'rsatkichda hukm YO'Q
   * (xom son); `null` — foiz bor, lekin o'lchanmagan.
   */
  rate?: number | null;
  thresholds?: RagThresholds;
  hint?: ReactNode;
}

/** Yuqoridagi ko'rsatkichlar lentasi: yorliq, katta raqam, svetofor hukmi. */
export function KpiReadout({ items, className }: { items: KpiItem[]; className?: string }) {
  if (items.length === 0) return null;
  return (
    <ul className={cn('grid grid-cols-2 gap-px bg-border lg:grid-cols-4', className)}>
      {items.map((item) => {
        const judged = item.rate !== undefined;
        const tone: Rag = judged ? rag(item.rate ?? null, item.thresholds ?? RATE_RAG) : 'yoq';
        return (
          <li key={item.label} className="flex min-w-0 flex-col gap-1 bg-surface px-3 py-2.5">
            <span className="flex items-center gap-2">
              {judged && tone !== 'yoq' && (
                <span aria-hidden="true" className={cn('h-2 w-2 shrink-0 rounded-[1px]', RAG_SOLID[tone])} />
              )}
              <MicroLabel className="truncate">{item.label}</MicroLabel>
            </span>
            <span className="flex items-baseline gap-1.5">
              <CodeText
                className={cn(
                  'text-[22px] font-semibold leading-none',
                  judged && tone !== 'yoq' ? RAG_TEXT[tone] : 'text-fg',
                )}
              >
                {item.value}
              </CodeText>
              {item.unit && <MicroLabel>{item.unit}</MicroLabel>}
            </span>
            {judged && tone !== 'yoq' && (
              <span className={cn('intel-code text-[11px]', RAG_TEXT[tone])}>{RAG_LABEL[tone]}</span>
            )}
            {item.hint && <span className="text-[11px] leading-snug text-muted">{item.hint}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/** Jadval katagidagi foiz: monoshrift raqam + Y/S/Q harfi.
 *  `note` — foiz umuman hisoblanmagan bo'lsa SABABI (bo'sh "—" emas). */
export function RateCell({
  value,
  note,
  thresholds = RATE_RAG,
  digits = 0,
}: {
  value: number | null;
  note?: string;
  thresholds?: RagThresholds;
  digits?: number;
}) {
  if (value === null || !Number.isFinite(value)) {
    return <span className="text-[11px] text-muted">{note ?? "o'lchanmagan"}</span>;
  }
  const tone = rag(value, thresholds);
  return (
    <span className="flex items-center justify-end gap-1.5">
      <CodeText className={cn('text-[13px] font-semibold', RAG_TEXT[tone])}>{value.toFixed(digits)}%</CodeText>
      <RagChip tone={tone} />
    </span>
  );
}

/**
 * Kunlik holatning qisqa belgisi — RANG YOLG'IZ QOLMASIN uchun.
 * Oq-qora bosmada ham, ranglarni ajratmaydigan o'quvchi uchun ham
 * belgining o'zi holatni aytadi.
 */
export const STATUS_MARK: Record<string, string> = {
  keldi: 'K',
  kech_keldi: 'KK',
  kelmadi: 'YQ',
  sababli: 'SB',
  kutilmoqda: 'KT',
  dam_olish: 'DO',
  malumot_yoq: '—',
  nomalum: '—',
};

const MARK_TONE: Record<string, string> = {
  keldi: 'bg-success-soft text-success',
  kech_keldi: 'bg-warning-soft text-warning',
  kelmadi: 'bg-danger-soft text-danger',
  sababli: 'bg-info-soft text-info',
  kutilmoqda: 'bg-surface-2 text-muted',
  dam_olish: 'bg-surface-2 text-subtle',
  malumot_yoq: 'bg-surface-2 text-subtle',
  nomalum: 'bg-surface-2 text-subtle',
};

/** Holat belgisi: harf + (ixtiyoriy) so'z. */
export function StatusMark({ status, label, showLabel = false }: { status: string; label: string; showLabel?: boolean }) {
  const mark = STATUS_MARK[status] ?? '—';
  const tone = MARK_TONE[status] ?? MARK_TONE.nomalum;
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span
        aria-hidden="true"
        className={cn('intel-code inline-flex min-w-[1.75rem] items-center justify-center rounded-[2px] px-1 py-0.5 text-[11px] font-bold', tone)}
      >
        {mark}
      </span>
      <span className={cn('text-[12px] text-muted', showLabel ? 'inline' : 'sr-only')}>{label}</span>
    </span>
  );
}

/** Ekrandagi sonlar eskirgan bo'lishi mumkin — chop etib yubormasin. */
export function StaleNote({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <p
      role="alert"
      className="print-hide flex flex-wrap items-center gap-2 border border-warning/50 bg-warning-soft px-3 py-2 text-[13px] text-fg"
    >
      <TriangleAlert size={15} aria-hidden="true" className="shrink-0" />
      <span>Ma&apos;lumot eskirgan: {message}</span>
      <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">
        Qayta urinish
      </button>
    </p>
  );
}

/** Chiziq bilan ajratilgan bo'lim sarlavhasi — suzib yurgan karta emas.
 *  Kurs bloklari va shunga o'xshash ichki guruhlar uchun. */
export function RuledSection({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-strong bg-surface-2 px-3 py-1.5">
        <h3 className="intel-micro !text-fg">{title}</h3>
        {meta && <span className="ms-auto">{meta}</span>}
      </header>
      {children}
    </section>
  );
}
