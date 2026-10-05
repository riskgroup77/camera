import { ChevronLeft, ChevronRight } from 'lucide-react';
import { IconButton, formatNumber } from '../../ui';

/** Jadval ostidagi sahifalash: "1–15 / 240" va oldingi/keyingi. */
export function Pager({ page, totalPages, total, pageSize, onChange }: { page: number; totalPages: number; total: number; pageSize: number; onChange: (page: number) => void }) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-[13px] text-muted">
      <span className="tabular-nums">
        {formatNumber(from)}–{formatNumber(to)} / {formatNumber(total)}
      </span>
      <div className="flex items-center gap-1">
        <IconButton icon={ChevronLeft} label="Oldingi sahifa" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)} />
        <span className="min-w-[4.5rem] text-center tabular-nums text-fg">
          {page} / {Math.max(1, totalPages)}
        </span>
        <IconButton icon={ChevronRight} label="Keyingi sahifa" size="sm" disabled={page >= totalPages} onClick={() => onChange(page + 1)} />
      </div>
    </div>
  );
}
