import { useRef, type KeyboardEvent } from 'react';
import { cn, focusRing } from '../../ui';
import { LAYOUT_LABELS, WALL_LAYOUTS, type WallLayout } from '../../lib/videoWall';

/** Setka tanlovi (1, 4, 9, 16, 25, 1+5, 1+7) — radio guruh, ← → bilan. */
export default function LayoutPicker({
  value,
  onChange,
  className,
}: {
  value: WallLayout;
  onChange: (layout: WallLayout) => void;
  className?: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let target: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') target = (index + 1) % WALL_LAYOUTS.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') target = (index - 1 + WALL_LAYOUTS.length) % WALL_LAYOUTS.length;
    if (target === null) return;
    // Sahifa darajasidagi ← → (sahifa almashtirish) ishlamasin.
    event.preventDefault();
    event.stopPropagation();
    refs.current[target]?.focus();
    onChange(WALL_LAYOUTS[target]);
  }

  return (
    <div
      role="radiogroup"
      aria-label="Setka"
      className={cn('inline-flex max-w-full gap-0.5 overflow-x-auto rounded-[2px] border border-border bg-surface-2 p-0.5 no-scrollbar', className)}
    >
      {WALL_LAYOUTS.map((layout, index) => {
        const active = value === layout;
        return (
          <button
            key={layout}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(layout)}
            onKeyDown={(event) => onKeyDown(event, index)}
            title={`${LAYOUT_LABELS[layout]} katak (${index + 1})`}
            className={cn(
              'intel-code h-8 min-w-[2.25rem] shrink-0 rounded-[2px] px-2 text-[12px] font-semibold transition-colors',
              focusRing,
              active ? 'border border-border-strong bg-surface text-fg' : 'text-muted hover:text-fg',
            )}
          >
            {LAYOUT_LABELS[layout]}
          </button>
        );
      })}
    </div>
  );
}
