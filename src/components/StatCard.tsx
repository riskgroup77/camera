import type { ReactNode } from 'react';

type Tone = 'indigo' | 'green' | 'red' | 'amber' | 'slate';

const SHADOW: Record<Tone, string> = {
  indigo: 'shadow-glass',
  green: 'shadow-glass-green',
  red: 'shadow-glass-red',
  amber: 'shadow-glass-amber',
  slate: 'shadow-glass',
};

const ICON_BG: Record<Tone, string> = {
  indigo: 'bg-indigo-100 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-400',
  green: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400',
  red: 'bg-red-100 text-red-600 dark:bg-red-500/15 dark:text-red-400',
  amber: 'bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400',
  slate: 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400',
};

interface StatCardProps {
  icon: ReactNode;
  value: ReactNode;
  label: string;
  sublabel?: string;
  tone?: Tone;
}

export default function StatCard({ icon, value, label, sublabel, tone = 'indigo' }: StatCardProps) {
  return (
    <div className={`glass flex items-center gap-4 p-5 ${SHADOW[tone]}`}>
      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${ICON_BG[tone]}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="truncate text-xl font-extrabold text-slate-900 dark:text-slate-100">{value}</p>
        <p className="truncate text-sm font-medium text-slate-600 dark:text-slate-400">{label}</p>
        {sublabel && <p className="truncate text-xs text-slate-400 dark:text-slate-500">{sublabel}</p>}
      </div>
    </div>
  );
}
