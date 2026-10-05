import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, SearchX } from 'lucide-react';
import { cn, focusRing } from './cn';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';
import { TONE_SOLID, type Tone } from './tones';
import { RAG_FILL, RAG_LABEL, RAG_LETTER, RAG_SOLID, type Rag } from './rag';
import { nextSort, sortRows, type SortDir, type SortState, type SortValue } from './tableSort';

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  /** Katak mazmuni. Berilmasa — `row[key]`. */
  cell?: (row: T, index: number) => ReactNode;
  /** Saralash qiymati. Berilsa ustun saralanadi. */
  sortValue?: (row: T) => SortValue;
  /** Birinchi bosishdagi yo'nalish (raqamlar uchun ko'pincha 'desc'). */
  sortFirst?: SortDir;
  align?: 'left' | 'center' | 'right';
  /** CSS kenglik ("8rem", "20%"). */
  width?: string;
  className?: string;
  /** Telefondagi kartada ko'rsatilmasin. */
  hideOnMobile?: boolean;
  /** Telefondagi kartadagi yorliq (standart: header). */
  mobileLabel?: string;
  /** Monoshriftni majburlash. O'ngga tekislangan ustunlarda avtomatik —
   *  bu bayroq markazdagi raqam/kod ustunlari uchun. */
  mono?: boolean;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  /** Tanlangan qator (Drawer ochiq bo'lsa). */
  selectedKey?: string | null;
  /** Qator chap chetidagi holat chizig'i. */
  rowTone?: (row: T) => Tone | null | undefined;
  /**
   * Qatorning svetofori. Berilsa jadval oldiga alohida HOLAT ustuni
   * qo'shiladi: rangli katak + harf (Y/S/Q) va qatorning chap qirrasi
   * bo'yaladi. Rang yolg'iz qolmaydi — harf va `title` doim yonida.
   */
  rowRag?: (row: T) => Rag | null | undefined;
  /** HOLAT ustunining sarlavhasi (standart: "Holat"). */
  ragHeader?: ReactNode;
  loading?: boolean;
  loadingRows?: number;
  error?: string | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  emptyAction?: ReactNode;
  /** Boshqariladigan saralash (server tomonida saralash uchun `manualSort` bilan). */
  sort?: SortState | null;
  onSortChange?: (sort: SortState | null) => void;
  defaultSort?: SortState | null;
  /** Qatorlar allaqachon saralangan (server) — lokal saralamaydi. */
  manualSort?: boolean;
  /** Jadval ichida aylantirish balandligi — sarlavha yopishib turadi. 'none' — cheklovsiz. */
  maxHeight?: string;
  /** Jadval ota elementining butun balandligini egallaydi va o'zi ichida
   *  aylanadi (sarlavha yopishib turadi). Ota element balandligi aniq
   *  bo'lishi kerak (masalan flex ichida `min-h-0 flex-1`). */
  fill?: boolean;
  dense?: boolean;
  /**
   * ESKI: juft/toq qatorlar foni. Yangi ko'rinishda qatorlar fon bilan
   * emas, ingichka chiziq bilan ajraladi — bayroq qabul qilinadi, lekin
   * hech narsa bo'yamaydi (chaqiruvchi kodni sindirmaslik uchun).
   */
  zebra?: boolean;
  /** Telefonda: 'cards' (standart) — har qator karta; 'scroll' — gorizontal aylantirish. */
  mobile?: 'cards' | 'scroll';
  /** Kartadagi sarlavha ustuni (standart: birinchi ustun). */
  mobileTitleKey?: string;
  ariaLabel?: string;
  /** Pastki qism (Pagination va h.k.). */
  footer?: ReactNode;
  className?: string;
}

const ALIGN = { left: 'text-left', center: 'text-center', right: 'text-right' } as const;
const JUSTIFY = { left: 'justify-start', center: 'justify-center', right: 'justify-end' } as const;

function defaultCell<T>(row: T, key: string): ReactNode {
  const value = (row as Record<string, unknown>)[key];
  if (value === null || value === undefined || value === '') return <span className="text-subtle">—</span>;
  return String(value);
}

/** Svetofor belgisi: rangli katak ichida harf + `title` bilan to'liq so'z. */
function RagMark({ value }: { value: Rag }) {
  return (
    <span
      title={RAG_LABEL[value]}
      className={cn(
        'intel-code inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[2px] px-1 text-[11px] font-bold leading-none',
        RAG_FILL[value],
      )}
    >
      {RAG_LETTER[value]}
      <span className="sr-only"> — {RAG_LABEL[value]}</span>
    </span>
  );
}

/** Ish jadvali: ingichka to'r, yopishqoq bosh harfli sarlavha, saralash,
 *  qator bosish (klaviatura bilan ham), svetofor ustuni, yuklanish/bo'sh/
 *  xato holatlari; telefonda — kartalar ro'yxati. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  rowTone,
  rowRag,
  ragHeader = 'Holat',
  loading = false,
  loadingRows = 6,
  error,
  onRetry,
  emptyTitle = "Ma'lumot topilmadi",
  emptyDescription,
  emptyAction,
  sort: controlledSort,
  onSortChange,
  defaultSort = null,
  manualSort = false,
  maxHeight = 'min(70vh, 48rem)',
  fill = false,
  dense = false,
  mobile = 'cards',
  mobileTitleKey,
  ariaLabel,
  footer,
  className,
}: DataTableProps<T>) {
  const [internalSort, setInternalSort] = useState<SortState | null>(defaultSort);
  // Aylantirilganda yopishqoq sarlavha mazmun USTIDA suzadi — shundagina
  // soya o'rinli (tinch turgan sirtlarda soya yo'q).
  const [scrolled, setScrolled] = useState(false);
  const sort = controlledSort !== undefined ? controlledSort : internalSort;

  function toggleSort(column: DataTableColumn<T>) {
    const next = nextSort(sort, column.key, column.sortFirst);
    if (controlledSort === undefined) setInternalSort(next);
    onSortChange?.(next);
  }

  const sortedRows = useMemo(() => {
    if (manualSort || !sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return rows;
    return sortRows(rows, column.sortValue, sort.dir);
  }, [rows, columns, sort, manualSort]);

  // Qator balandligi ~32px (zich holatda ~26px).
  const cellPad = dense ? 'px-2 py-1' : 'px-2.5 py-1.5';
  const headPad = dense ? 'px-2 py-1.5' : 'px-2.5 py-2';
  const showEmpty = !loading && !error && sortedRows.length === 0;

  function rowKeyDown(event: KeyboardEvent<HTMLElement>, row: T) {
    if (!onRowClick) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowClick(row);
    }
  }

  const titleColumn = columns.find((c) => c.key === mobileTitleKey) ?? columns[0];
  const mobileColumns = columns.filter((c) => c !== titleColumn && !c.hideOnMobile);

  /** Ustun matni monoshriftdami: o'ngga tekislangan (raqam) yoki majburlangan. */
  const isMono = (column: DataTableColumn<T>) => column.mono || column.align === 'right';

  // Yopishqoq sarlavha: engil fon, tartib aniq, lekin jadval qattiq hujjatdek ko'rinmaydi.
  const headCell = cn(
    'sticky top-0 z-10 border-b border-border bg-surface-2/95 backdrop-blur transition-shadow',
    scrolled && 'shadow-[0_8px_14px_-12px_rgb(42_72_130/0.28)]',
  );

  const tableView = (
    <div
      data-table-scroll=""
      className={cn('overflow-auto', fill && 'min-h-0 flex-1', mobile === 'cards' && 'hidden md:block')}
      style={maxHeight !== 'none' && !fill ? { maxHeight } : undefined}
      onScroll={(event) => {
        const next = event.currentTarget.scrollTop > 0;
        if (next !== scrolled) setScrolled(next);
      }}
    >
      <table
        className="w-full border-separate border-spacing-0 text-[13px]"
        aria-label={ariaLabel}
        aria-busy={loading || undefined}
      >
        <thead>
          <tr>
            {rowRag && (
              <th scope="col" style={{ width: '3.5rem' }} className={cn(headCell, headPad, 'text-center')}>
                <span className="intel-micro intel-micro-wrap !text-fg">{ragHeader}</span>
              </th>
            )}
            {columns.map((column) => {
              const sortable = Boolean(column.sortValue);
              const active = sort?.key === column.key;
              const SortIcon = active ? (sort?.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
              const align = column.align ?? 'left';
              return (
                <th
                  key={column.key}
                  scope="col"
                  style={column.width ? { width: column.width } : undefined}
                  aria-sort={active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : sortable ? 'none' : undefined}
                  className={cn(headCell, headPad, 'border-r border-r-border last:border-r-0', ALIGN[align])}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column)}
                      className={cn('-mx-1 inline-flex max-w-full items-center gap-1 rounded-[2px] px-1 py-0.5', focusRing, JUSTIFY[align])}
                    >
                      <span className={cn('intel-micro intel-micro-wrap', active ? '!text-fg' : '!text-muted')}>{column.header}</span>
                      <SortIcon size={11} aria-hidden="true" className={cn('shrink-0', active ? 'text-primary' : 'text-subtle opacity-60')} />
                    </button>
                  ) : (
                    <span className="intel-micro intel-micro-wrap">{column.header}</span>
                  )}
                </th>
              );
            })}
            {onRowClick && <th aria-hidden="true" className={cn(headCell, 'w-7')} />}
          </tr>
        </thead>
        <tbody>
          {loading &&
            Array.from({ length: loadingRows }).map((_, r) => (
              <tr key={`sk-${r}`}>
                {rowRag && (
                  <td className={cn(cellPad, 'border-b border-r border-border')}>
                    <Skeleton className="mx-auto h-3.5 w-4" />
                  </td>
                )}
                {columns.map((column, c) => (
                  <td key={column.key} className={cn(cellPad, 'border-b border-r border-border last:border-r-0')}>
                    <Skeleton className={cn('h-3', c === 0 ? 'w-3/4' : 'w-1/2', column.align === 'right' && 'ml-auto')} />
                  </td>
                ))}
                {onRowClick && <td className="border-b border-border" />}
              </tr>
            ))}
          {!loading &&
            sortedRows.map((row, index) => {
              const key = rowKey(row, index);
              const tone = rowTone?.(row);
              const ragValue = rowRag?.(row);
              const selected = selectedKey === key;
              return (
                <tr
                  key={key}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={onRowClick ? (event) => rowKeyDown(event, row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  aria-selected={onRowClick ? selected : undefined}
                  className={cn(
                    'group transition-colors duration-150',
                    // Hover — zaif ko'k tus, fon almashinuvi emas.
                    onRowClick && 'cursor-pointer hover:bg-primary/[0.045] focus-visible:bg-primary/[0.08] focus-visible:outline-none',
                    selected && 'bg-primary-soft hover:bg-primary-soft',
                  )}
                >
                  {ragValue && (
                    <td className={cn(cellPad, 'relative border-b border-r border-border text-center align-middle')}>
                      <span className={cn('absolute inset-y-0 left-0 w-[3px]', RAG_SOLID[ragValue])} aria-hidden="true" />
                      <RagMark value={ragValue} />
                    </td>
                  )}
                  {columns.map((column, c) => (
                    <td
                      key={column.key}
                      className={cn(
                        cellPad,
                        'relative border-b border-r border-border align-middle text-fg last:border-r-0',
                        ALIGN[column.align ?? 'left'],
                        isMono(column) && 'intel-code',
                        column.className,
                      )}
                    >
                      {c === 0 && !ragValue && tone && (
                        <span className={cn('absolute inset-y-0 left-0 w-[3px]', TONE_SOLID[tone])} aria-hidden="true" />
                      )}
                      {column.cell ? column.cell(row, index) : defaultCell(row, column.key)}
                    </td>
                  ))}
                  {onRowClick && (
                    <td className="border-b border-border pr-2 text-subtle">
                      <ChevronRight
                        size={14}
                        aria-hidden="true"
                        className="-translate-x-1 opacity-0 transition-[opacity,transform] group-hover:translate-x-0 group-hover:opacity-100 group-focus-visible:opacity-100"
                      />
                    </td>
                  )}
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );

  const cardsView = mobile === 'cards' && (
    <ul data-table-cards="" className="divide-y divide-border md:hidden" aria-label={ariaLabel} aria-busy={loading || undefined}>
      {loading &&
        Array.from({ length: Math.min(loadingRows, 4) }).map((_, r) => (
          <li key={`sk-${r}`} className="space-y-2 p-3">
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
          </li>
        ))}
      {!loading &&
        sortedRows.map((row, index) => {
          const key = rowKey(row, index);
          const tone = rowTone?.(row);
          const ragValue = rowRag?.(row);
          const content = (
            <>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 text-[13px] font-semibold text-fg">
                  {titleColumn.cell ? titleColumn.cell(row, index) : defaultCell(row, titleColumn.key)}
                </div>
                {ragValue && <RagMark value={ragValue} />}
                {onRowClick && <ChevronRight size={14} className="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />}
              </div>
              {mobileColumns.length > 0 && (
                <dl className="mt-1.5 flex flex-col gap-1">
                  {mobileColumns.map((column) => (
                    <div key={column.key} className="flex min-w-0 items-center justify-between gap-3">
                      <dt className="intel-micro shrink-0">{column.mobileLabel ?? column.header}</dt>
                      <dd className="intel-code min-w-0 truncate text-right text-[12px] text-fg">
                        {column.cell ? column.cell(row, index) : defaultCell(row, column.key)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          );
          const edge = ragValue ? RAG_SOLID[ragValue] : tone ? TONE_SOLID[tone] : null;
          return (
            <li key={key} className="relative">
              {edge && <span className={cn('absolute inset-y-0 left-0 w-[3px]', edge)} aria-hidden="true" />}
              {onRowClick ? (
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onRowClick(row)}
                  onKeyDown={(event) => rowKeyDown(event, row)}
                  className={cn(
                    'block w-full p-3 text-left transition-colors hover:bg-primary/[0.045]',
                    selectedKey === key && 'bg-primary-soft',
                    focusRing,
                  )}
                >
                  {content}
                </div>
              ) : (
                <div className="p-3">{content}</div>
              )}
            </li>
          );
        })}
    </ul>
  );

  return (
    <div className={cn('min-w-0 overflow-hidden rounded-card border border-white/90 bg-surface shadow-card', fill && 'flex h-full flex-col', className)}>
      {error ? (
        <ErrorState variant="block" message={error} onRetry={onRetry} />
      ) : (
        <>
          {tableView}
          {cardsView}
          {showEmpty && (
            <EmptyState icon={SearchX} title={emptyTitle} description={emptyDescription} action={emptyAction} compact bordered={false} />
          )}
        </>
      )}
      {footer && <div className="border-t border-border px-3 py-2">{footer}</div>}
    </div>
  );
}
