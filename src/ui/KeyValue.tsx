import type { ReactNode } from 'react';
import { cn } from './cn';

export interface KeyValueItem {
  label: ReactNode;
  value: ReactNode;
  /** Qiymat ostida kichik izoh. */
  hint?: ReactNode;
}

const COLUMNS = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
  4: 'grid-cols-2 lg:grid-cols-4',
} as const;

/** Nom → qiymat ro'yxati (<dl>). `layout="inline"` — nom chapda, qiymat o'ngda
 *  (tor panellar, Drawer uchun); `stacked` — nom ustida (kartalar uchun). */
export function KeyValue({
  items,
  columns = 1,
  layout = 'inline',
  className,
}: {
  items: KeyValueItem[];
  columns?: keyof typeof COLUMNS;
  layout?: 'inline' | 'stacked';
  className?: string;
}) {
  if (layout === 'inline') {
    return (
      <dl className={cn('divide-y divide-border', className)}>
        {items.map((item, index) => (
          <div key={index} className="flex items-start justify-between gap-4 py-1.5 first:pt-0 last:pb-0">
            <dt className="intel-micro intel-micro-wrap shrink-0 pt-0.5">{item.label}</dt>
            <dd className="intel-code min-w-0 text-right text-[13px] font-medium text-fg">
              {item.value ?? '—'}
              {item.hint && <p className="mt-0.5 text-[11px] font-normal text-muted">{item.hint}</p>}
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl className={cn('grid gap-x-5 gap-y-3', COLUMNS[columns], className)}>
      {items.map((item, index) => (
        <div key={index} className="min-w-0 border-l-2 border-border pl-2">
          <dt className="intel-micro intel-micro-wrap">{item.label}</dt>
          <dd className="intel-code mt-0.5 break-words text-[13px] font-medium text-fg">
            {item.value ?? '—'}
            {item.hint && <p className="mt-0.5 text-[11px] font-normal text-muted">{item.hint}</p>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
