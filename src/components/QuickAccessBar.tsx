import { Link } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Video,
  BrainCircuit,
  FileBarChart,
  ScrollText,
} from 'lucide-react';

const QUICK_LINKS = [
  { to: '/admin', label: 'Boshqaruv paneli', icon: LayoutDashboard },
  { to: '/admin/students-staff', label: 'Talabalar va Xodimlar', icon: Users },
  { to: '/admin/cameras', label: 'Kameralar va Zonalar', icon: Video },
  { to: '/admin/ai-modules', label: 'AI Modullari', icon: BrainCircuit },
  { to: '/admin/reports', label: 'Hisobotlar', icon: FileBarChart },
  { to: '/admin/system-log', label: 'Tizim jurnali', icon: ScrollText },
];

export default function QuickAccessBar() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
        Tezkor kirish
      </span>
      {QUICK_LINKS.map(({ to, label, icon: Icon }) => (
        <Link
          key={to}
          to={to}
          title={label}
          className="btn-glass flex items-center gap-1.5 !px-2.5"
        >
          <Icon size={14} />
          <span className="hidden sm:inline">{label}</span>
        </Link>
      ))}
    </div>
  );
}
