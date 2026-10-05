import { cn } from '../../ui';

/**
 * Bosiladigan sanoqlar: "Kech keldi 37" ni bossangiz — aynan kimlar
 * (chaqiruvchi ro'yxatni shu holat bilan filtrlaydi yoki oyna ochadi).
 */

export type CounterKey =
  | 'hammasi'
  | 'kelgan'
  | 'kech_keldi'
  | 'kelmadi'
  | 'kutilmoqda'
  | 'yuzsiz'
  | 'darsda'
  | 'darsda_emas';

export const COUNTER_META: Record<CounterKey, { label: string; hint: string; tone: string }> = {
  hammasi: { label: 'Jami', hint: 'Ro‘yxatdagi hamma', tone: 'text-fg' },
  kelgan: { label: 'Keldi', hint: 'Bugun kamera ko‘rgan (kech kelganlar bilan)', tone: 'text-success' },
  kech_keldi: { label: 'Kech keldi', hint: 'Belgilangan vaqtdan keyin kelgan', tone: 'text-warning' },
  kelmadi: { label: 'Kelmadi', hint: 'Kelmadi deb belgilangan', tone: 'text-danger' },
  kutilmoqda: { label: 'Hali kelmagan', hint: 'Yuzi bazada, bugun hali ko‘rinmagan', tone: 'text-muted' },
  yuzsiz: { label: 'Yuzi bazada yo‘q', hint: 'Kamera tanimaydi — ro‘yxatdan o‘tishi kerak', tone: 'text-danger' },
  darsda: { label: 'Darsda', hint: 'Hozirgi darsda kamera ko‘rgan', tone: 'text-success' },
  darsda_emas: { label: 'Darsda yo‘q', hint: 'Hozirgi darsda ko‘rinmagan', tone: 'text-danger' },
};

export interface CounterItem {
  key: CounterKey;
  value: number | null;
}

export default function StatusCounters({
  items,
  active,
  onPick,
  size = 'md',
  className,
}: {
  items: CounterItem[];
  active?: CounterKey | null;
  onPick: (key: CounterKey) => void;
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <div className={cn('grid gap-1.5', className)} style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${size === 'sm' ? 86 : 104}px, 1fr))` }}>
      {items.map(({ key, value }) => {
        const meta = COUNTER_META[key];
        const on = active === key;
        return (
          <button
            key={key}
            type="button"
            title={meta.hint}
            onClick={() => onPick(key)}
            aria-pressed={on}
            className={cn(
              'flex min-w-0 flex-col items-start rounded-control border px-2.5 py-1.5 text-left transition-colors',
              on ? 'border-primary bg-primary-soft' : 'border-border bg-surface hover:border-primary/50 hover:bg-surface-2',
            )}
          >
            <span className={cn('tabular-nums font-semibold leading-tight', size === 'sm' ? 'text-[18px]' : 'text-[22px]', meta.tone)}>
              {value ?? '—'}
            </span>
            <span className="truncate text-[11px] font-medium text-muted">{meta.label}</span>
          </button>
        );
      })}
    </div>
  );
}
