import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Building2,
  Video,
  BrainCircuit,
  ShieldCheck,
  ScrollText,
  FileBarChart,
  Siren,
  CalendarCheck,
  Presentation,
  LogOut,
  Bell,
  Menu,
  X,
} from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';
import { usePermissions, type PermissionKey } from '../lib/permissions';
import { useLiveEvents } from '../lib/realtime';

const NAV_ITEMS: {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
  permission?: PermissionKey;
}[] = [
  { to: '/admin', label: 'Boshqaruv paneli', icon: LayoutDashboard, end: true },
  { to: '/admin/events', label: 'Hodisalar jurnali', icon: Siren },
  { to: '/admin/students-staff', label: 'Talabalar va Xodimlar', icon: Users, permission: 'registerPeople' },
  { to: '/admin/attendance', label: 'Davomat kalendari', icon: CalendarCheck },
  { to: '/admin/teaching', label: 'Dars monitoring', icon: Presentation },
  { to: '/admin/org-structure', label: 'Tashkiliy tuzilma', icon: Building2 },
  { to: '/admin/cameras', label: 'Kameralar va Zonalar', icon: Video, permission: 'manageCameras' },
  { to: '/admin/ai-modules', label: 'AI Modullari', icon: BrainCircuit, permission: 'configureAi' },
  { to: '/admin/reports', label: 'Hisobotlar', icon: FileBarChart, permission: 'viewReports' },
  { to: '/admin/users-roles', label: 'Foydalanuvchilar va Rollar', icon: ShieldCheck, permission: 'manageRoles' },
  { to: '/admin/system-log', label: 'Tizim jurnali', icon: ScrollText, permission: 'systemSettings' },
];

const ROLE_LABEL = { 'super-admin': 'Super Admin', admin: 'Admin' } as const;

export default function AdminLayout() {
  const navigate = useNavigate();
  const { role, userName, logout } = useAuth();
  const { can } = usePermissions();
  const [unreadEvents, setUnreadEvents] = useState(0);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useLiveEvents(() => setUnreadEvents((n) => n + 1));

  const visibleItems = NAV_ITEMS.filter((item) => !item.permission || can(item.permission, role));

  function handleLogout() {
    logout();
    navigate('/admin/login', { replace: true });
  }

  function handleBellClick() {
    setUnreadEvents(0);
    navigate('/admin/events');
  }

  return (
    <div className="flex min-h-screen bg-canvas dark:bg-[#0a0f1e]">
      {mobileNavOpen && (
        <div
          onClick={() => setMobileNavOpen(false)}
          className="fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={`glass-deep fixed inset-y-0 left-0 z-40 m-3 flex w-64 shrink-0 flex-col rounded-2xl p-4 transition-transform duration-200 lg:static lg:translate-x-0 ${
          mobileNavOpen ? 'translate-x-0' : '-translate-x-[120%]'
        }`}
      >
        <div className="mb-6 flex items-center justify-between px-1">
          <div>
            <p className="text-sm font-extrabold leading-tight text-slate-900 dark:text-slate-100">
              Farg'ona JSSTI
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">Situatsion Markaz</p>
          </div>
          <button
            onClick={() => setMobileNavOpen(false)}
            aria-label="Menyuni yopish"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-white/60 hover:text-slate-700 dark:hover:bg-white/10 lg:hidden"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {visibleItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMobileNavOpen(false)}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'nav-item-active' : ''}`
              }
            >
              <Icon size={18} strokeWidth={2} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {userName && role && (
          <div className="mb-2 flex items-center gap-2 rounded-xl bg-white/50 px-3 py-2 text-xs dark:bg-white/5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-400">
              {userName.slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="truncate font-semibold text-slate-800 dark:text-slate-200">{userName}</p>
              <p className="text-slate-400 dark:text-slate-500">{ROLE_LABEL[role]}</p>
            </div>
          </div>
        )}

        <button onClick={handleLogout} className="glass-btn-danger">
          <LogOut size={16} />
          Tizimdan chiqish
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="mx-3 mt-3 flex items-center justify-between rounded-2xl glass-deep px-5 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setMobileNavOpen(true)}
              aria-label="Menyuni ochish"
              className="glass-deep shrink-0 rounded-xl p-2 text-slate-500 hover:text-indigo-500 dark:text-slate-400 dark:hover:text-indigo-400 lg:hidden"
            >
              <Menu size={18} />
            </button>
            <AdminBreadcrumb items={visibleItems} />
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 rounded-full bg-emerald-100/80 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400 sm:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Tizim faol
            </span>
            <ThemeToggle />
            <button
              onClick={handleBellClick}
              aria-label={unreadEvents > 0 ? `${unreadEvents} ta yangi hodisa` : 'Bildirishnomalar'}
              title={unreadEvents > 0 ? `${unreadEvents} ta yangi hodisa` : 'Bildirishnomalar'}
              className="relative glass-deep rounded-xl p-2 text-slate-500 transition-colors hover:text-indigo-500 dark:text-slate-400 dark:hover:text-indigo-400"
            >
              <Bell size={18} />
              {unreadEvents > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                  {unreadEvents > 9 ? '9+' : unreadEvents}
                </span>
              )}
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 p-3">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function AdminBreadcrumb({ items }: { items: typeof NAV_ITEMS }) {
  const { pathname } = useLocation();
  const current =
    items.find((item) => (item.end ? pathname === item.to : pathname.startsWith(item.to))) ??
    items[0];

  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
      <span>Farg'ona JSSTI</span>
      <span>/</span>
      <span className="font-semibold text-slate-900 dark:text-slate-100">{current?.label}</span>
    </div>
  );
}
