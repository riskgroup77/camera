import { MicroLabel, cn } from '../../ui';
import {
  RAG_FILL,
  RAG_LABEL,
  RAG_LETTER,
  RAG_SOLID,
  RAG_TEXT,
  RATE_RAG,
  rag,
  type Rag,
  type RagThresholds,
} from '../../ui/rag';

/**
 * Holat taxtasi — rahbar uchun asosiy ekran.
 *
 * Har katak bitta bo'linma: chap qirrasida svetofor chizig'i, ichida
 * nomi va katta raqam. Yomoni birinchi turadi — ko'z avval chora
 * kerak bo'lgan joyni ko'radi.
 *
 * Rang YOLG'IZ ma'no tashimaydi: har katakda harf (Y/S/Q) ham bor.
 */

export interface BoardItem {
  id: string;
  name: string;
  /** Asosiy son. null — o'lchanmagan. */
  value: number | null;
  /** '%' bo'lsa svetofor ishlaydi; 'ta' bo'lsa faqat ustun uzunligi. */
  unit: string;
  /** Ikkinchi qator: "142/160 keldi". */
  detail: string | null;
  headcount: number | null;
}

/** Foiz bo'lmagan ko'rsatkichga svetofor QO'YILMAYDI: "12 ta kechikish"
 *  yaxshimi yoki yomonmi — bo'linma kattaligini bilmasdan aytib
 *  bo'lmaydi, rang esa aniq hukm degani. */
export function boardRag(item: BoardItem, thresholds: RagThresholds): Rag {
  if (item.unit !== '%') return 'yoq';
  return rag(item.value, thresholds);
}

function formatValue(value: number | null, unit: string): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const rounded = unit === '%' ? Math.round(value * 10) / 10 : value;
  return `${rounded.toLocaleString('ru-RU')}${unit === '%' ? '%' : ''}`;
}

export function StatusBoard({
  items,
  thresholds = RATE_RAG,
  onOpen,
  emptyText = "Bu davr uchun bo'linma ma'lumoti yo'q",
}: {
  items: BoardItem[];
  thresholds?: RagThresholds;
  onOpen?: (id: string) => void;
  emptyText?: string;
}) {
  if (items.length === 0) {
    return <p className="px-3 py-6 text-center text-[13px] text-muted">{emptyText}</p>;
  }
  const max = Math.max(...items.map((i) => (i.value === null ? 0 : Math.abs(i.value))), 1);

  return (
    <ul className="grid grid-cols-1 gap-px bg-border sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
      {items.map((item) => {
        const tone = boardRag(item, thresholds);
        const share = item.value === null ? 0 : Math.min(100, (Math.abs(item.value) / max) * 100);
        const clickable = Boolean(onOpen);
        return (
          <li key={item.id} className="bg-surface">
            <button
              type="button"
              disabled={!clickable}
              onClick={clickable ? () => onOpen?.(item.id) : undefined}
              className={cn(
                'flex w-full items-stretch gap-3 px-3 py-2.5 text-left',
                clickable && 'hover:bg-primary-soft focus-visible:bg-primary-soft',
                !clickable && 'cursor-default',
              )}
              title={`${item.name} — ${RAG_LABEL[tone]}`}
            >
              {/* Svetofor chizig'i — katakning chap qirrasi. */}
              <span aria-hidden="true" className={cn('w-1 shrink-0 rounded-[1px]', RAG_SOLID[tone])} />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="min-w-0 truncate text-[13px] font-medium text-fg">{item.name}</span>
                <span className="flex items-baseline gap-2">
                  <span className={cn('intel-code text-[20px] font-semibold leading-none', RAG_TEXT[tone])}>
                    {formatValue(item.value, item.unit)}
                  </span>
                  <span className={cn('intel-code text-[10px] font-bold', RAG_TEXT[tone])} title={RAG_LABEL[tone]}>
                    {RAG_LETTER[tone]}
                  </span>
                  {item.headcount !== null && (
                    <MicroLabel className="ms-auto">{item.headcount.toLocaleString('ru-RU')} kishi</MicroLabel>
                  )}
                </span>
                {/* Ustun uzunligi — eng katta qiymatga nisbatan. */}
                <span aria-hidden="true" className="h-[3px] w-full bg-surface-3">
                  <span className={cn('block h-full', RAG_SOLID[tone])} style={{ width: `${share}%` }} />
                </span>
                {item.detail && <span className="truncate text-[11px] text-muted">{item.detail}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** Svetofor qoidasi — bitta qator. */
export function RagLegend({ thresholds = RATE_RAG }: { thresholds?: RagThresholds; unit?: string }) {
  const bands: Rag[] = ['yashil', 'sariq', 'qizil'];
  const text: Record<Rag, string> = {
    yashil: `${thresholds.ok}% dan`,
    sariq: `${thresholds.warn}% dan`,
    qizil: `${thresholds.warn}% dan past`,
    yoq: '',
  };
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-1.5">
      {bands.map((band) => (
        <span key={band} className="flex items-center gap-1.5">
          <span aria-hidden="true" className={cn('h-2.5 w-2.5 rounded-[1px]', RAG_SOLID[band])} />
          <span className="intel-code text-[11px] text-muted">
            {RAG_LETTER[band]} {text[band]}
          </span>
        </span>
      ))}
    </div>
  );
}

/** Jadval qatoridagi kichik svetofor yorlig'i. */
export function RagChip({ tone, className }: { tone: Rag; className?: string }) {
  return (
    <span
      title={RAG_LABEL[tone]}
      className={cn(
        'intel-code inline-flex min-w-[1.5rem] items-center justify-center rounded-[2px] px-1 py-0.5 text-[11px] font-bold',
        RAG_FILL[tone],
        className,
      )}
    >
      {RAG_LETTER[tone]}
    </span>
  );
}
