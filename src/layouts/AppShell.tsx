import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, type Role } from '../lib/auth';
import { usePermissions } from '../lib/permissions';
import { useLiveEvents } from '../lib/realtime';
import { signalAlarm } from '../lib/alarmSignal';
import { usePersistedState } from '../lib/usePersistedState';
import { VIEW_DATE_PARAM, useViewDate } from '../lib/viewDate';
import DayOffNotice from '../components/situation/DayOffNotice';
import { ButtonLink, EmptyState, PageSkeleton, cn } from '../ui';
import { ShellContext, type Crumb, type PageMeta } from '../ui/pageContext';
import { ROLE_LABEL, findActive, homeForRole, isPathAllowedForRole, usesViewDate, visibleSections } from './shell/navConfig';
import { CommandPalette } from './shell/CommandPalette';
import { useCommandPaletteHotkey } from './shell/useCommandPaletteHotkey';
import { Sidebar } from './shell/Sidebar';
import { Topbar } from './shell/Topbar';
import { usePresentation } from './shell/usePresentation';
import { ShieldAlert } from 'lucide-react';

/** Tizimga kirgandan keyingi YAGONA maket: chapda menyu, tepada panel
 *  (non-yo'l, sana, soat, holat, hodisalar, mavzu, taqdimot, foydalanuvchi),
 *  o'rtada sahifa. Sahifalar `Page` shabloni bilan chiziladi. */
export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { role, userName, logout } = useAuth();
  const { can } = usePermissions();

  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [collapsed, setCollapsed] = usePersistedState<boolean>('shell-sidebar-collapsed', false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const presentation = usePresentation();
  const [searchOpen, setSearchOpen] = useState(false);
  const toggleSearch = useCallback(() => setSearchOpen((v) => !v), []);
  useCommandPaletteHotkey(toggleSearch, !presentation.active);

  // Hodisalarni ko'rish huquqi bo'lmasa, server WebSocket'ni baribir yopadi
  // (4403) — ulanishga umuman urinmaymiz. event_updated — mavjud hodisaning
  // holati o'zgargani, yangi hodisa emas.
  const canReviewEvents = can('reviewEvents', role);
  const [unreadEvents, setUnreadEvents] = useState(0);
  const liveStatus = useLiveEvents((event) => {
    if (event.kind !== 'event_updated') setUnreadEvents((n) => n + 1);
    signalAlarm(event);
  }, canReviewEvents);

  useEffect(() => {
    setMobileNavOpen(false);
    setSearchOpen(false);
  }, [location.pathname]);

  // Hodisalar sahifasiga QANDAY kelinganidan qat'i nazar hisoblagich
  // tozalanadi. Ilgari u faqat qo'ng'iroq tugmasi bosilganda tozalanardi:
  // menyudan (yoki xatcho'pdan) kirilsa, ro'yxat allaqachon ko'z oldida
  // turgan bo'lsa ham qizil "12" osilib qolaverardi.
  useEffect(() => {
    if (location.pathname === '/hodisalar') setUnreadEvents(0);
  }, [location.pathname]);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setMobileNavOpen(false);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mobileNavOpen]);

  const canKey = useCallback((key: Parameters<typeof can>[0]) => can(key, role), [can, role]);
  const sections = useMemo(() => visibleSections(canKey, role), [canKey, role]);

  const exitPresentation = presentation.exit;
  const handleLogout = useCallback(() => {
    exitPresentation();
    logout();
    navigate('/kirish', { replace: true });
  }, [logout, navigate, exitPresentation]);

  const openEvents = useCallback(() => {
    setUnreadEvents(0);
    navigate('/hodisalar');
  }, [navigate]);

  const shellValue = useMemo(() => ({ setPageMeta: setMeta, presentation: presentation.active, inShell: true }), [presentation.active]);

  const crumbs: Crumb[] = useMemo(() => {
    if (meta?.crumbs && meta.crumbs.length > 0) return meta.crumbs;
    const active = findActive(location.pathname);
    if (!active) return meta ? [{ label: meta.title }] : [];
    if (active.item.to === '/') return [{ label: meta?.title ?? active.item.label }];
    return [{ label: active.section.label }, { label: meta?.title ?? active.item.label }];
  }, [meta, location.pathname]);

  // Cheklangan rol (kamera mas'uli) ruxsat etilmagan manzilga tushsa
  // (URL'ni qo'lda yozdi, eski havola, brauzer tarixi) — SABABI AYTILADI.
  //
  // Ilgari bu yerda jimgina `<Navigate>` bor edi: foydalanuvchi bosgan
  // havolasi hech qanday izohsiz boshqa sahifaga "sakrab" ketardi va u
  // buni sahifa buzilgan deb tushunardi. Endi menyu va panel joyida
  // qoladi, o'rtada esa tushunarli xabar va bosh sahifaga tugma.
  const pathBlocked = !isPathAllowedForRole(role, location.pathname);

  const rawDate = params.get(VIEW_DATE_PARAM);
  const linkSuffix = rawDate ? `?${VIEW_DATE_PARAM}=${encodeURIComponent(rawDate)}` : '';
  const showDate = usesViewDate(location.pathname);

  return (
    <ShellContext.Provider value={shellValue}>
      <div className="flex min-h-screen bg-bg">
        <a
          href="#asosiy"
          className="sr-only z-[70] bg-primary px-3 py-2 text-sm font-semibold text-primary-fg focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Asosiy qismga o'tish
        </a>
        {!presentation.active && (
          <Sidebar
            sections={sections}
            collapsed={collapsed}
            mobileOpen={mobileNavOpen}
            onCloseMobile={() => setMobileNavOpen(false)}
            userName={userName}
            role={role}
            onLogout={handleLogout}
            linkSuffix={linkSuffix}
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar
            crumbs={crumbs}
            showDate={showDate}
            onOpenMobileNav={() => setMobileNavOpen(true)}
            mobileNavOpen={mobileNavOpen}
            sidebarCollapsed={collapsed}
            onToggleSidebar={() => setCollapsed((value) => !value)}
            presentation={presentation}
            bell={{ enabled: canReviewEvents, count: unreadEvents, onOpen: openEvents }}
            userName={userName}
            role={role}
            onLogout={handleLogout}
            onOpenSearch={() => setSearchOpen(true)}
            wallScreen={can('viewReports', role) || can('manageAttendance', role)}
            live={liveStatus}
          />
          <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} sections={sections} can={canKey} role={role} />
          <main id="asosiy" tabIndex={-1} className={cn('flex min-w-0 flex-1 flex-col outline-none', presentation.active ? 'p-5' : 'px-3 py-4 sm:px-5 lg:px-6 lg:py-5')}>
            <div className={cn('mx-auto flex w-full min-w-0 flex-1 flex-col', !presentation.active && 'max-w-[1600px]')}>
              {pathBlocked ? (
                <EmptyState
                  icon={ShieldAlert}
                  title="Bu sahifa sizning rolingiz uchun ochiq emas"
                  description={`${ROLE_LABEL[role as Role] ?? 'Rolingiz'} faqat o'ziga tegishli bo'limlar bilan ishlaydi. Kerakli bo'lim chap menyuda; boshqasiga kirish kerak bo'lsa, Super Admin'ga murojaat qiling.`}
                  action={<ButtonLink variant="primary" to={homeForRole(role)}>Ishchi sahifaga qaytish</ButtonLink>}
                />
              ) : (
                /* Sahifa bo'lagi yuklanayotganda menyu va panel joyida qoladi. */
                <Suspense fallback={<PageSkeleton />}>
                  {usesViewDate(location.pathname) && <ViewDateDayOff />}
                  <Outlet />
                </Suspense>
              )}
            </div>
          </main>
        </div>
      </div>
    </ShellContext.Provider>
  );
}


/** Sanaga bog'liq sahifalar ustida: tanlangan kun dam olish/bayram bo'lsa ogohlantirish. */
function ViewDateDayOff() {
  const { date, setDate } = useViewDate();
  return <DayOffNotice date={date} onPick={setDate} className="mb-3" />;
}
