import { Link, useLocation, useNavigate, Outlet } from 'react-router-dom';
import { LogIn, LogOut, ScanFace } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';
import QuickAccessBar from '../components/QuickAccessBar';
import { useAuth } from '../lib/auth';

export default function PublicLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { role, logout } = useAuth();
  const onEnrollment = location.pathname === '/royxatdan-otish';
  const onMonitoring = location.pathname === '/';

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-canvas dark:bg-[#0a0f1e]">
      <header className="glass mx-3 mt-3 shrink-0 space-y-3 rounded-2xl px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[15px] font-extrabold leading-tight text-slate-900 dark:text-slate-100">
              Farg'ona jamoat salomatligi tibbiyot instituti
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">Situatsion Markaz</p>
          </div>
          <div className="flex items-center gap-3">
            {!onEnrollment && (
              <Link
                to="/royxatdan-otish"
                className="inline-flex items-center gap-1.5 rounded-full bg-indigo-100/80 px-3 py-1 text-xs font-semibold text-indigo-700 transition-colors hover:bg-indigo-200/80 dark:bg-indigo-500/10 dark:text-indigo-400 dark:hover:bg-indigo-500/20"
              >
                <ScanFace size={13} />
                Yuzni ro'yxatdan o'tkazish
              </Link>
            )}
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100/80 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Jonli yangilanish
            </span>
            <ThemeToggle />
            {/* Tizimga kirmagan foydalanuvchiga "Chiqish" deb turish
                chalg'ituvchi edi — tugma aslida kirish sahifasiga olib
                boradi. Endi yozuv ham, belgi ham, rangi ham holatga mos. */}
            <button
              onClick={() => {
                if (role) logout();
                navigate('/admin/login');
              }}
              className={`flex items-center gap-1.5 !py-2 ${role ? 'glass-btn-danger' : 'btn-glass'}`}
            >
              {role ? <LogOut size={14} /> : <LogIn size={14} />}
              {role ? 'Chiqish' : 'Kirish'}
            </button>
          </div>
        </div>

        {onMonitoring && (
          <div className="border-t border-white/70 pt-3 dark:border-white/10">
            <QuickAccessBar />
          </div>
        )}
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-3">
        <Outlet />
      </main>
    </div>
  );
}
