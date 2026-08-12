import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function Pagination({
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
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs">
      <span className="text-slate-400 dark:text-slate-500">
        {from}–{to} / {total} ta yozuv
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="Oldingi sahifa"
          className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/70 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-400 dark:hover:bg-white/10"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="px-2 font-semibold text-slate-700 dark:text-slate-300">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Keyingi sahifa"
          className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/70 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-400 dark:hover:bg-white/10"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
