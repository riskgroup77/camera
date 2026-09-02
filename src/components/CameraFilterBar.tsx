export interface CameraFilters {
  building: string;
  status: string;
}

export const EMPTY_FILTERS: CameraFilters = {
  building: '',
  status: '',
};

interface CameraFilterBarProps {
  filters: CameraFilters;
  onChange: (filters: CameraFilters) => void;
  buildings: string[];
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-xl border border-white/80 bg-white/60 px-3 py-2 text-sm font-medium normal-case text-slate-700 outline-none focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:focus:border-indigo-500"
      >
        <option value="">Barchasi</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Kameralar ro'yxatini filtrlaydigan boshqaruvlar — MonitoringPage'dagi
 * "Smart Filtr" bloki shu komponentdan iborat. Faqat haqiqatan
 * ko'rsatilayotgan kameralarni filtrlaydi (bino, holat); ular bilan
 * bevosita bog'liq bo'lmagan alohida statistik ko'rsatkichlar endi
 * bu yerda yo'q. */
export default function CameraFilterBar({ filters, onChange, buildings }: CameraFilterBarProps) {
  const set = (key: keyof CameraFilters) => (value: string) =>
    onChange({ ...filters, [key]: value });

  const hasActiveFilters = Object.values(filters).some(Boolean);

  return (
    <div className="flex flex-wrap items-end gap-3">
      <Select label="O'quv korpusi" value={filters.building} options={buildings} onChange={set('building')} />
      <Select label="Kamera holati" value={filters.status} options={['JONLI', 'OFLAYN']} onChange={set('status')} />

      {hasActiveFilters && (
        <button
          onClick={() => onChange(EMPTY_FILTERS)}
          className="rounded-xl px-3 py-2 text-xs font-semibold text-indigo-600 transition-colors hover:bg-white/60 dark:text-indigo-400 dark:hover:bg-white/5"
        >
          Filtrlarni tozalash
        </button>
      )}
    </div>
  );
}
