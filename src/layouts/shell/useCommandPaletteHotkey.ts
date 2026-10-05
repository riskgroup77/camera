import { useEffect } from 'react';

/** Ctrl/⌘+K — palitrani ochish/yopish (matn kiritish maydonida ham ishlaydi). */
export function useCommandPaletteHotkey(toggle: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && (event.key === 'k' || event.key === 'K' || event.code === 'KeyK')) {
        event.preventDefault();
        toggle();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [toggle, enabled]);
}
