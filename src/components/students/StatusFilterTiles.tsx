import { CodeText, MicroLabel, cn, focusRing, formatNumber, TONE_SOLID, type Tone } from '../../ui';
import type { StudentFilter } from '../../lib/studentAttendance';

export interface FilterTile<T extends string = StudentFilter> {
  id: T;
  label: string;
  value: number;
  tone: Tone;
}

/**
 * Holatlar bo'yicha sonlar — bir vaqtda ham ko'rsatkich, ham filtr:
 * bosilganda ro'yxat shu holatdagilarga toraytiriladi.
 *
 * Kataklar chiziq bilan ajraladi (soya va bo'shliq emas), raqamlar
 * monoshriftda — ustma-ust turganda ular bir chiziqda o'qiladi.
 * Bu XOM SON, foiz emas: unga svetofor hukmi qo'yilmaydi, faqat
 * holatning o'z rangi (keldi/kech/kelmadi) ko'rsatiladi.
 */
export function StatusFilterTiles<T extends string = StudentFilter>({
  tiles,
  total,
  value,
  onChange,
  big = false,
}: {
  tiles: FilterTile<T>[];
  total: number;
  value: T;
  onChange: (value: T) => void;
  big?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Holat bo'yicha filtr"
      className={cn('grid gap-px bg-border', tiles.length <= 3 ? 'grid-cols-3' : 'grid-cols-2 min-[520px]:grid-cols-3 lg:grid-cols-6')}
    >
      {tiles.map((tile) => {
        const active = tile.id === value;
        const share = total > 0 && tile.id !== 'all' ? Math.round((tile.value / total) * 100) : null;
        // Nol plitkani bosish har doim bo'sh ro'yxat berardi — o'chirib qo'yiladi.
        const empty = tile.value === 0 && !active && tile.id !== 'all';
        return (
          <button
            key={tile.id}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={empty}
            title={empty ? `${tile.label}: 0 — filtrlash uchun hech kim yo'q` : undefined}
            onClick={() => onChange(active && tile.id !== 'all' ? ('all' as T) : tile.id)}
            className={cn(
              'flex min-w-0 flex-col gap-1 px-3 py-2 text-left transition-colors',
              active ? 'bg-primary-soft shadow-[inset_2px_0_0_rgb(var(--c-primary))]' : 'bg-surface hover:bg-surface-2',
              empty && 'cursor-default bg-surface text-subtle opacity-60 hover:bg-surface',
              focusRing,
            )}
          >
            <span className="flex min-w-0 items-center gap-1.5">
              {tile.id !== 'all' && <span className={cn('h-2 w-2 shrink-0 rounded-[1px]', TONE_SOLID[tile.tone])} aria-hidden="true" />}
              <MicroLabel className="truncate">{tile.label}</MicroLabel>
            </span>
            <span className="flex items-baseline gap-1.5">
              <CodeText className={cn('font-semibold leading-none text-fg', big ? 'text-[28px]' : 'text-[22px]')}>
                {formatNumber(tile.value)}
              </CodeText>
              {share !== null && <CodeText className="text-[11px] text-subtle">{share}%</CodeText>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
