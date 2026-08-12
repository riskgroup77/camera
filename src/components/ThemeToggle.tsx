import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/useTheme';

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();

  return (
    <button
      onClick={toggle}
      title={theme === 'dark' ? "Yorug' rejim" : 'Tungi rejim'}
      aria-label={theme === 'dark' ? "Yorug' rejimga o'tish" : "Tungi rejimga o'tish"}
      className="glass-deep rounded-xl p-2 text-slate-500 transition-colors hover:text-indigo-500 dark:text-slate-400 dark:hover:text-indigo-400"
    >
      {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
