import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, BellOff, LayoutGrid, LogOut, MonitorSmartphone, ShieldCheck, Volume2, VolumeX } from 'lucide-react';
import TwoFactorModal from '../components/admin/TwoFactorModal';
import { isBackendConfigured } from '../lib/config';
import {
  alarmSoundEnabled,
  desktopNotificationsState,
  playAlarmTone,
  requestDesktopNotifications,
  setAlarmSoundEnabled,
} from '../lib/alarmSignal';
import { useAuth } from '../lib/auth';
import { usePermissions } from '../lib/permissions';
import { ROLE_LABEL, visibleSections } from '../layouts/shell/navConfig';
import { Menu, cn, focusRing, type MenuEntry } from '../ui';

/**
 * Konsoldan boshqa bo'limlarga yo'l va chiqish.
 *
 * Konsolda yon menyu ataylab yo'q (bitta oyna), lekin undan boshqa
 * sahifaga faqat manzilni qo'lda terib o'tish mumkin edi, chiqish
 * tugmasi esa umuman yo'q edi. Menyu AppShell bilan AYNAN bir xil
 * ro'yxatdan (navConfig) — huquq va rol bo'yicha filtrlangan.
 */

const triggerClass =
  'flex h-10 items-center gap-1.5 rounded-control bg-surface-2 px-3 text-[13px] font-semibold text-fg transition-colors hover:bg-primary-soft';

export function ConsoleSectionsMenu() {
  const { role } = useAuth();
  const { can } = usePermissions();
  const canKey = useCallback((key: Parameters<typeof can>[0]) => can(key, role), [can, role]);

  const items = useMemo<MenuEntry[]>(() => {
    const entries: MenuEntry[] = [];
    for (const section of visibleSections(canKey, role)) {
      const links = section.items.filter((item) => item.to !== '/');
      if (!links.length) continue;
      if (entries.length) entries.push('separator');
      for (const item of links) entries.push({ label: item.label, icon: item.icon, to: item.to });
    }
    return entries;
  }, [canKey, role]);

  if (!items.length) return null;
  return (
    <Menu
      width="w-72"
      items={items}
      trigger={(props) => (
        <button type="button" {...props} className={cn(triggerClass, focusRing)} aria-label="Bo‘limlar">
          <LayoutGrid size={15} aria-hidden="true" />
          <span className="hidden md:inline">Bo‘limlar</span>
        </button>
      )}
    />
  );
}

export function ConsoleUserMenu() {
  const { role, userName, logout } = useAuth();
  const navigate = useNavigate();
  const initials = (userName ?? '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('');

  const [sound, setSound] = useState(alarmSoundEnabled);
  const [desktop, setDesktop] = useState(desktopNotificationsState);
  const [twoFactorOpen, setTwoFactorOpen] = useState(false);

  const items: MenuEntry[] = [
    {
      label: sound ? 'Signal ovozi: yoqilgan' : 'Signal ovozi: o‘chirilgan',
      icon: sound ? Volume2 : VolumeX,
      onSelect: () => {
        const next = !sound;
        setAlarmSoundEnabled(next);
        setSound(next);
        if (next) playAlarmTone();
      },
    },
    ...(desktop === 'unsupported'
      ? []
      : [
          {
            label:
              desktop === 'granted'
                ? 'Ish stoli bildirishnomasi: yoqilgan'
                : desktop === 'denied'
                  ? 'Bildirishnoma brauzerda bloklangan'
                  : 'Ish stoli bildirishnomasini yoqish',
            icon: desktop === 'granted' ? Bell : desktop === 'denied' ? BellOff : MonitorSmartphone,
            disabled: desktop !== 'default',
            onSelect: () => void requestDesktopNotifications().then(setDesktop),
          } satisfies MenuEntry,
        ]),
    // Demo rejimda (backendsiz) 2FA ma'nosiz — server yo'q.
    ...(isBackendConfigured
      ? [{ label: 'Ikki bosqichli kirish', icon: ShieldCheck, onSelect: () => setTwoFactorOpen(true) } satisfies MenuEntry]
      : []),
    'separator',
    {
      label: 'Chiqish',
      icon: LogOut,
      danger: true,
      onSelect: () => {
        logout();
        navigate('/kirish', { replace: true });
      },
    },
  ];

  return (
    <>
      <Menu
        items={items}
        header={
          <span className="flex flex-col">
            <b className="truncate text-[13px] text-fg">{userName ?? 'Foydalanuvchi'}</b>
            {role && <small className="text-[11px] text-muted">{ROLE_LABEL[role]}</small>}
          </span>
        }
        trigger={(props) => (
          <button
            type="button"
            {...props}
            aria-label="Foydalanuvchi menyusi"
            className={cn(
              'grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-soft text-[12px] font-bold text-primary transition-colors hover:bg-primary/15',
              focusRing,
            )}
          >
            {initials || '?'}
          </button>
        )}
      />
      {twoFactorOpen && <TwoFactorModal open onClose={() => setTwoFactorOpen(false)} />}
    </>
  );
}
