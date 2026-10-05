import { ChevronLeft, ChevronRight } from 'lucide-react';
import { IconButton, formatNumber } from '../../ui';

/** Server sahifalash: "21–40 / 312 ta" va oldingi/keyingi. Bitta sahifada — ko'rinmaydi. */
export default function EventsPager({
  page,
  totalPages,
  total,
  pageSize,
  onChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav aria-label="Sahifalar" className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted">
      <span className="tabular-nums">
        {formatNumber(from)}–{formatNumber(to)} / {formatNumber(total)} ta yozuv
      </span>
      <span className="flex items-center gap-1">
        <IconButton icon={ChevronLeft} size="sm" variant="secondary" label="Oldingi sahifa" disabled={page <= 1} onClick={() => onChange(page - 1)} />
        <span className="px-2 font-medium tabular-nums text-fg">
          {page} / {totalPages}
        </span>
        <IconButton icon={ChevronRight} size="sm" variant="secondary" label="Keyingi sahifa" disabled={page >= totalPages} onClick={() => onChange(page + 1)} />
      </span>
    </nav>
  );
}
