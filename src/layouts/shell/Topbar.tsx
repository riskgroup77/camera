import { useState } from 'react';
import { LogOut, Menu as MenuIcon, Minimize2, MonitorUp, PanelLeftClose, PanelLeftOpen, Presentation, Search, ShieldCheck } from 'lucide-react';
import TwoFactorModal from '../../components/admin/TwoFactorModal';
import { branding } from '../../lib/branding';
import type { Role } from '../../lib/auth';
import { isBackendConfigured } from '../../lib/config';
import type { LiveStatus } from '../../lib/realtime';
import { useViewDate } from '../../lib/viewDate';
import { Avatar, Button, DatePicker, IconButton, Menu, cn, focusRing, formatUzDate, type Crumb } from '../../ui';
import { MicroLabel } from '../../ui/intel';
import { ROLE_LABEL, openWallScreen } from './navConfig';
import { BrandMark } from './Sidebar';
import { Breadcrumbs, ConnectionLamp, EventsBell, LiveClock, SystemStatus } from './TopbarWidgets';

/**
 * Yuqori panel — ASBOBLAR CHIZIG'I, bezak emas.
 *
 * Chapda manzil chizig'i (non-yo'l), o'ngda: Toshkent soati (sekundlari
 * bilan), ulanish chirog'i, tizim holati, hodisalar qo'ng'irog'i, sana.
 * Bitta ixcham qator, ostida bitta ingichka chiziq. Har chiroq yonida
 * so'z bor — rang yolg'iz ma'no tashimaydi.
 */

interface TopbarProps {
  crumbs: Crumb[];
  showDate: boolean;
  onOpenMobileNav: () => void;
  mobileNavOpen: boolean;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  presentation: { active: boolean; toggle: () => void; exit: () => void };
  bell: { enabled: boolean; count: number; onOpen: () => void };
  userName: string | null;
  role: Role | null;
  onLogout: () => void;
  /** Global qidiruvni (Ctrl/⌘+K) ochish. */
  onOpenSearch?: () => void;
  /** Devor ekrani (/markaz-ekran) ko'rsatilsinmi (huquq bo'yicha). */
  wallScreen?: boolean;
  /** Jonli (WebSocket) ulanish holati — uzilganini AYTISH shart. */
  live?: LiveStatus;
}

const IS_MAC = typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent);

/** Asboblar orasidagi ingichka ajratgich. */
function Rule() {
  return <span className="hidden h-5 w-px shrink-0 bg-border md:block" aria-hidden="true" />;
}

function SearchTrigger({ onOpen }: { onOpen: () => void }) {
  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        aria-label="Qidirish (Ctrl+K)"
        aria-keyshortcuts="Control+K Meta+K"
        className={cn(
          'hidden h-7 w-44 items-center gap-2 border border-border bg-surface-2 px-2 text-left transition-colors hover:border-border-strong hover:bg-surface lg:inline-flex xl:w-56',
          focusRing,
        )}
      >
        <Search size={13} aria-hidden="true" className="shrink-0 text-subtle" />
        <MicroLabel className="flex-1">Qidiruv</MicroLabel>
        <kbd className="intel-code border border-border bg-surface px-1 py-px text-[10px] font-medium text-muted">{IS_MAC ? '⌘K' : 'CTRL K'}</kbd>
      </button>
      <IconButton icon={Search} label="Qidirish" size="sm" onClick={onOpen} className="lg:hidden" />
    </>
  );
}

function ViewDateControl({ compact }: { compact?: boolean }) {
  const { date, setDate } = useViewDate();
  return <DatePicker value={date} onChange={setDate} quick={!compact} stepper size="sm" compact={compact} ariaLabel="Ko'rilayotgan sana" className="min-w-0" />;
}

export function Topbar({ crumbs, showDate, onOpenMobileNav, mobileNavOpen, sidebarCollapsed, onToggleSidebar, presentation, bell, userName, role, onLogout, onOpenSearch, wallScreen, live = 'off' }: TopbarProps) {
  const [twoFactorOpen, setTwoFactorOpen] = useState(false);

  if (presentation.active) {
    return <PresentationBar crumbs={crumbs} showDate={showDate} onExit={presentation.exit} bell={bell} live={live} />;
  }

  return (
    <header
      data-print="hide"
      className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-border-strong bg-surface px-2 sm:gap-3 sm:px-4"
    >
      <IconButton
        icon={MenuIcon}
        label="Menyuni ochish"
        size="sm"
        onClick={onOpenMobileNav}
        aria-expanded={mobileNavOpen}
        aria-controls="app-sidebar"
        className="lg:hidden"
      />
      <IconButton
        icon={sidebarCollapsed ? PanelLeftOpen : PanelLeftClose}
        label={sidebarCollapsed ? 'Menyuni kengaytirish' : "Menyuni yig'ish"}
        size="sm"
        onClick={onToggleSidebar}
        aria-expanded={!sidebarCollapsed}
        aria-controls="app-sidebar"
        className="hidden lg:inline-flex"
      />

      {/* Manzil chizig'i. */}
      <div className="min-w-0 flex-1">
        <Breadcrumbs crumbs={crumbs} />
      </div>

      {onOpenSearch && <SearchTrigger onOpen={onOpenSearch} />}

      {showDate && (
        <>
          <div className="hidden sm:block">
            <ViewDateControl />
          </div>
          <div className="sm:hidden">
            <ViewDateControl compact />
          </div>
        </>
      )}

      <Rule />

      {/* O'lchov guruhi: vaqt, ulanish, tizim. */}
      <div className="hidden items-center gap-3 md:flex">
        <LiveClock seconds className="text-[13px]" />
        <ConnectionLamp status={live} />
        <SystemStatus showLabel={!showDate} />
      </div>

      <Rule />

      <div className="flex items-center gap-0.5">
        {bell.enabled && <EventsBell count={bell.count} onOpen={bell.onOpen} />}
        {wallScreen && <IconButton icon={MonitorUp} size="sm" label="Katta ekran (devor) — yangi oynada" onClick={openWallScreen} className="hidden md:inline-flex" />}
        <IconButton icon={Presentation} size="sm" label="Taqdimot rejimi (joriy sahifa to'liq ekranda)" onClick={presentation.toggle} className="hidden md:inline-flex" />
      </div>

      {userName && role && (
        <Menu
          width="w-64"
          header={
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-fg">{userName}</p>
              <MicroLabel>{ROLE_LABEL[role]}</MicroLabel>
            </div>
          }
          items={[
            { label: 'Taqdimot rejimi', icon: Presentation, onSelect: presentation.toggle },
            ...(wallScreen ? [{ label: 'Katta ekran (devor)', icon: MonitorUp, onSelect: openWallScreen }] : []),
            // Demo rejimda (backendsiz) 2FA ma'nosiz — server yo'q.
            ...(isBackendConfigured ? [{ label: 'Ikki bosqichli kirish', icon: ShieldCheck, onSelect: () => setTwoFactorOpen(true) }] : []),
            'separator',
            { label: 'Tizimdan chiqish', icon: LogOut, danger: true, onSelect: onLogout },
          ]}
          trigger={(props) => (
            <button {...props} type="button" aria-label={`Foydalanuvchi menyusi: ${userName}`} className={cn('shrink-0', focusRing)}>
              <Avatar name={userName} size="sm" />
            </button>
          )}
        />
      )}
      {twoFactorOpen && <TwoFactorModal open onClose={() => setTwoFactorOpen(false)} />}
    </header>
  );
}

/** Devor ekrani uchun yuqori panel: katta soat, sana, sahifa nomi, chiqish. */
function PresentationBar({ crumbs, showDate, onExit, bell, live = 'off' }: { crumbs: Crumb[]; showDate: boolean; onExit: () => void; bell: TopbarProps['bell']; live?: LiveStatus }) {
  const { date } = useViewDate();
  const title = crumbs[crumbs.length - 1]?.label;
  return (
    <header data-print="hide" className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-4 border-b border-border-strong bg-surface px-5">
      <BrandMark className="h-9 w-9" />
      <div className="min-w-0 leading-tight">
        <p className="truncate text-[13px] font-semibold text-fg">{branding.orgName}</p>
        <MicroLabel>{branding.systemName}</MicroLabel>
      </div>
      {title && (
        <>
          <span className="h-8 w-px bg-border" aria-hidden="true" />
          <h2 className="truncate text-lg font-semibold tracking-tight text-fg">{title}</h2>
        </>
      )}
      <div className="flex-1" />
      {showDate && <span className="intel-code hidden text-[13px] text-muted md:inline">{formatUzDate(date, { weekday: true })}</span>}
      <LiveClock seconds className="text-2xl" />
      <ConnectionLamp status={live} />
      <SystemStatus showLabel={false} />
      {bell.enabled && <EventsBell count={bell.count} onOpen={bell.onOpen} />}
      <Button variant="secondary" size="sm" icon={Minimize2} onClick={onExit} title="Taqdimot rejimidan chiqish (Esc)">
        Chiqish
      </Button>
    </header>
  );
}
