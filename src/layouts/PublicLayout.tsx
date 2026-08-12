import { Outlet } from 'react-router-dom';
import ThemeToggle from '../components/ThemeToggle';

export default function PublicLayout() {
  return (
    <div className="min-h-screen bg-canvas dark:bg-[#0a0f1e]">
      <header className="glass mx-3 mt-3 flex items-center justify-between rounded-2xl px-6 py-4">
        <div>
          <h1 className="text-[15px] font-extrabold leading-tight text-slate-900 dark:text-slate-100">
            Farg'ona jamoat salomatligi tibbiyot instituti
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">Situatsion Markaz</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100/80 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
            Jonli yangilanish
          </span>
          <ThemeToggle />
        </div>
      </header>

      <main className="p-3">
        <Outlet />
      </main>
    </div>
  );
}
