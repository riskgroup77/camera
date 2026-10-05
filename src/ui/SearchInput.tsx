import { Search, X } from 'lucide-react';
import { cn, controlBase, controlSizes, focusRing, type ControlSize } from './cn';

export interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Standart: placeholder. */
  ariaLabel?: string;
  size?: ControlSize;
  autoFocus?: boolean;
  className?: string;
}

/** Qidiruv: tozalash tugmasi va Esc bilan tozalash. Serverga so'rovni
 *  kechiktirish (debounce) chaqiruvchida — lib/useDebouncedValue. */
export function SearchInput({ value, onChange, placeholder = 'Qidirish…', ariaLabel, size = 'md', autoFocus, className }: SearchInputProps) {
  return (
    <div className={cn('relative w-full min-w-[12rem] sm:max-w-xs', className)}>
      <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value) {
            event.preventDefault();
            onChange('');
          }
        }}
        placeholder={placeholder}
        aria-label={ariaLabel ?? placeholder}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        className={cn('intel-code', controlBase, controlSizes[size], 'pl-8 pr-8 [&::-webkit-search-cancel-button]:hidden')}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label="Qidiruvni tozalash"
          className={cn('absolute right-1 top-1/2 -translate-y-1/2 rounded-[2px] p-1 text-subtle hover:bg-surface-2 hover:text-fg', focusRing)}
        >
          <X size={13} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
