import { Suspense } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { LogIn, ShieldCheck } from 'lucide-react';
import { branding } from '../lib/branding';
import { useAuth } from '../lib/auth';
import { ButtonLink, PageSkeleton } from '../ui';
import { MicroLabel } from '../ui/intel';
import { BrandMark } from './shell/Sidebar';

/** Tizimga kirmasdan ochiladigan sahifalar uchun sodda maket:
 *  - `center` — kirish va parolni tiklash (markazdagi HUJJAT varag'i:
 *    tashkilot satri, burchak qisqichlari, ingichka chiziqlar — reklama
 *    kartasi emas, rasmiy blank);
 *  - `page` — ochiq ro'yxatdan o'tish (tepada nom va "Kirish"). */
export default function MinimalLayout({ variant = 'center' }: { variant?: 'center' | 'page' }) {
  const { role } = useAuth();

  if (variant === 'page') {
    return (
      <div className="flex min-h-screen flex-col bg-bg">
        <header className="border-b border-border-strong bg-surface">
          <div className="mx-auto flex h-12 max-w-5xl items-center gap-2.5 px-4">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <BrandMark />
              <span className="min-w-0 leading-tight">
                <span className="block truncate text-[13px] font-semibold tracking-tight text-fg">{branding.orgName}</span>
                <MicroLabel className="block truncate">{branding.systemName}</MicroLabel>
              </span>
            </Link>
            <div className="flex-1" />
            <ButtonLink to={role ? '/' : '/kirish'} size="sm" icon={role ? undefined : LogIn}>
              {role ? 'Bosh sahifa' : 'Kirish'}
            </ButtonLink>
          </div>
        </header>
        <main className="flex-1 px-4 py-6">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-bg px-4 py-10">
      {/* O'lchov to'ri — juda zaif, shovqinsiz fon. */}
      <div aria-hidden="true" className="intel-grid pointer-events-none absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" />

      <div className="relative w-full max-w-[420px]">
        {/* Hujjat blanki: tashkilot satri va burchak qisqichlari. */}
        <div className="intel-panel intel-brackets">
          <div className="flex items-start gap-3 border-b border-border-strong px-4 py-3">
            <BrandMark />
            <div className="min-w-0 flex-1 leading-tight">
              <MicroLabel className="block truncate">{branding.systemName}</MicroLabel>
              <p className="mt-0.5 text-[13px] font-semibold leading-snug tracking-tight text-fg">{branding.orgFullName}</p>
            </div>
          </div>
          <div className="px-4 py-4">
            <Suspense fallback={<PageSkeleton />}>
              <Outlet />
            </Suspense>
          </div>
        </div>

        <p className="mt-3 flex items-center justify-center gap-1.5">
          <ShieldCheck size={12} aria-hidden="true" className="text-subtle" />
          <MicroLabel>Ulanish shifrlangan (HTTPS)</MicroLabel>
        </p>
      </div>
    </div>
  );
}
