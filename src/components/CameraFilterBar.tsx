import { AlertTriangle, Clock3, Video, VideoOff } from 'lucide-react';

export interface CameraFilters {
  building: string;
  status: string;
}

export const EMPTY_FILTERS: CameraFilters = {
  building: '',
  status: '',
};

interface QuickStats {
  live: number;
  risk: number;
  offline: number;
  late: number;
}

interface CameraFilterBarProps {
  filters: CameraFilters;
  onChange: (filters: CameraFilters) => void;
  stats: QuickStats;
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

export default function CameraFilterBar({ filters, onChange, stats, buildings }: CameraFilterBarProps) {
  const set = (key: keyof CameraFilters) => (value: string) =>
    onChange({ ...filters, [key]: value });

  const hasActiveFilters = Object.values(filters).some(Boolean);

  return (
    <div className="mb-5 space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <QuickStat icon={<Video size={16} />} value={stats.live} label="Jonli" tone="green" />
        <QuickStat icon={<AlertTriangle size={16} />} value={stats.risk} label="Xavf" tone="red" />
        <QuickStat icon={<VideoOff size={16} />} value={stats.offline} label="Oflayn" tone="slate" />
        <QuickStat icon={<Clock3 size={16} />} value={stats.late} label="Kechikish" tone="amber" />
      </div>

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
    </div>
  );
}

function QuickStat({
  icon,
  value,
  label,
  tone,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
  tone: 'green' | 'red' | 'slate' | 'amber';
}) {
  const TONE_CLASSES: Record<typeof tone, string> = {
    green: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400',
    red: 'bg-red-100 text-red-600 dark:bg-red-500/15 dark:text-red-400',
    slate: 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400',
    amber: 'bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400',
  };
  return (
    <div className="glass-deep flex items-center gap-2.5 px-3 py-2.5">
      <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${TONE_CLASSES[tone]}`}>
        {icon}
      </span>
      <div>
        <p className="text-base font-extrabold leading-none text-slate-900 dark:text-slate-100">{value}</p>
        <p className="text-[11px] text-slate-500 dark:text-slate-400">{label}</p>
      </div>
    </div>
  );
}
