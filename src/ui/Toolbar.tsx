import type { ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import { Button } from './Button';
import { cn } from './cn';
import { SearchInput } from './SearchInput';
import { Select } from './Select';
import { isFilterActive, presentFilterFields, resetFilterFields, type FilterFieldEntry } from './filterFields';

export interface ToolbarProps {
  /** Filtrlar: SearchInput, Select, DatePicker... (chapdan). */
  children: ReactNode;
  /** O'ng tomonda (masalan "Eksport", ko'rinish almashtirgich). */
  end?: ReactNode;
  /** Faol filtrlar soni — 0 dan katta bo'lsa "Tozalash" chiqadi. */
  activeCount?: number;
  onReset?: () => void;
  /** Aylantirilganda yuqorida yopishib turadi. */
  sticky?: boolean;
  className?: string;
}

/** Filtrlar qatori — har sahifada bir xil joyda (sarlavha/tablar ostida)
 *  va bir xil ko'rinishda. Telefonda elementlar qatorlarga o'raladi. */
export function Toolbar({ children, end, activeCount = 0, onReset, sticky = false, className }: ToolbarProps) {
  return (
    <div
      role="toolbar"
      aria-label="Filtrlar"
      className={cn(
        // Asboblar qatori — hujjatning boshqaruv chizig'i: oq lenta,
        // tepasi va pasti ingichka chiziq bilan chegaralangan.
        'flex flex-wrap items-center gap-1.5 border-y border-border bg-surface px-2 py-1.5',
        sticky && 'sticky top-14 z-20',
        className,
      )}
    >
      {children}
      {onReset && activeCount > 0 && (
        <Button variant="ghost" size="sm" icon={RotateCcw} onClick={onReset}>
          Tozalash ({activeCount})
        </Button>
      )}
      {end && <div className="ml-auto flex flex-wrap items-center gap-1.5">{end}</div>}
    </div>
  );
}

/* FilterBar — filtr qatorining umumiy qobig'i. Maydon turlari va sanash
 * mantig'i ./filterFields.ts'da (sof mantiq, alohida sinaladi). */

export interface FilterBarProps {
  fields: readonly FilterFieldEntry[];
  end?: ReactNode;
  sticky?: boolean;
  className?: string;
  /** Tozalashni sahifa o'zi bajarsin (masalan bitta URL yozuvida bir
   *  nechta parametrni birdan o'chirish kerak bo'lganda). Berilmasa
   *  har bir maydon alohida standart holatiga qaytariladi. */
  onReset?: () => void;
}

/** Filtrlar qatori: sanash va tozalash barcha sahifalarda bir xil. */
export function FilterBar({ fields, end, sticky, className, onReset }: FilterBarProps) {
  const present = presentFilterFields(fields);
  const activeCount = present.filter(isFilterActive).length;
  const reset = onReset ?? (() => resetFilterFields(present));

  return (
    <Toolbar activeCount={activeCount} onReset={reset} end={end} sticky={sticky} className={className}>
      {present.map((field, index) => {
        if (field.kind === 'custom') {
          return (
            <span key={index} className="contents">
              {field.render}
            </span>
          );
        }
        if (field.kind === 'search') {
          return (
            <SearchInput
              key={index}
              value={field.value}
              onChange={field.onChange}
              placeholder={field.placeholder}
              ariaLabel={field.ariaLabel}
              className={field.className}
            />
          );
        }
        // `<select>` uchun "hammasi" doim bo'sh satr (placeholder option).
        // Sahifada u 'all' kabi boshqa qiymat bo'lishi mumkin — o'girib
        // beramiz, aks holda qiymat hech bir option'ga tushmay qolardi.
        const inactive = field.inactiveValue ?? '';
        return (
          <Select
            key={index}
            value={field.value === inactive ? '' : field.value}
            onChange={(value) => field.onChange(value === '' ? inactive : value)}
            options={field.options}
            placeholder={field.placeholder}
            label={field.label}
            ariaLabel={field.ariaLabel}
            className={field.className}
            highlightActive
          />
        );
      })}
    </Toolbar>
  );
}
