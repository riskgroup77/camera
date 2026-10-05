import { NavLink, useLocation } from 'react-router-dom';
import { LogOut, ScanEye, Star, X } from 'lucide-react';
import { usePersistedState } from '../../lib/usePersistedState';
import { branding } from '../../lib/branding';
import type { Role } from '../../lib/auth';
import { IconButton, cn, focusRing } from '../../ui';
import { ROLE_LABEL, matchesPath, usesViewDate, type NavItem, type NavSection } from './navConfig';

/** Yon menyu — faqat belgi va to'liq nom. Ichki qisqartmalar foydalanuvchiga
 * kerak emas, shuning uchun hech qayerda ko'rsatilmaydi. */

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn('flex h-8 w-8 shrink-0 items-center justify-center border border-primary bg-primary text-primary-fg', className)}
      aria-hidden="true"
    >
      <ScanEye size={17} strokeWidth={2.1} />
    </span>
  );
}

interface SidebarProps {
  sections: NavSection[];
  collapsed: boolean;
  /** Telefon: off-canvas panel ochiqmi. */
  mobileOpen: boolean;
  onCloseMobile: () => void;
  userName: string | null;
  role: Role | null;
  onLogout: () => void;
  /** Tanlangan sana (`?sana=...`) davomat bo'limlari havolalarida saqlanadi. */
  linkSuffix: string;
}

export function Sidebar({ sections, collapsed, mobileOpen, onCloseMobile, userName, role, onLogout, linkSuffix }: SidebarProps) {
  const { pathname } = useLocation();
  // Telefondagi off-canvas panel doim to'liq (yig'ilmagan) holatda.
  const rail = collapsed && !mobileOpen;
  // Foydalanuvchi tanlovlari brauzerda (usePersistedState — try/catch bilan).
  const [favorites, setFavorites] = usePersistedState<string[]>('shell-nav-favorites', []);
  const [collapsedSections, setCollapsedSections] = usePersistedState<string[]>('shell-nav-collapsed', []);
  const safeFavorites = Array.isArray(favorites) ? favorites : [];
  const allItems = sections.flatMap((section) => section.items);
  // Tartib — foydalanuvchi qo'shgan tartibda; huquqi yo'qolgan sahifa ko'rinmaydi.
  const favoriteItems = safeFavorites.map((to) => allItems.find((item) => item.to === to)).filter((item): item is NavItem => Boolean(item));

  const toggleSection = (id: string) =>
    setCollapsedSections((prev) => {
      const list = Array.isArray(prev) ? prev : [];
      return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
    });
  const toggleFavorite = (to: string) =>
    setFavorites((prev) => {
      const list = Array.isArray(prev) ? prev : [];
      return list.includes(to) ? list.filter((x) => x !== to) : [...list, to];
    });

  const itemProps: NavItemSharedProps = { pathname, rail, linkSuffix, onNavigate: onCloseMobile, favorites: safeFavorites, onToggleFavorite: toggleFavorite };

  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-40 animate-fade-in bg-black/40 lg:hidden" onClick={onCloseMobile} aria-hidden="true" />}
      <aside
        data-print="hide"
        id="app-sidebar"
        aria-label="Asosiy menyu"
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-[17rem] flex-col border-r border-border bg-surface transition-[width,transform] duration-150 ease-out lg:sticky lg:top-0 lg:z-30 lg:h-screen lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : 'invisible -translate-x-full lg:visible',
          rail ? 'lg:w-[4rem]' : 'lg:w-[15.5rem]',
        )}
      >
        {/* Tashkilot satri — hujjat blankining yuqori qismi kabi. */}
        <div className={cn('flex h-12 shrink-0 items-center gap-2.5 border-b border-border-strong', rail ? 'justify-center px-2' : 'px-3')}>
          <BrandMark />
          {!rail && (
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-[13px] font-semibold tracking-tight text-fg">{branding.orgName}</p>
              <p className="intel-micro truncate">{branding.systemName}</p>
            </div>
          )}
          {mobileOpen && <IconButton icon={X} label="Menyuni yopish" size="sm" onClick={onCloseMobile} className="lg:hidden" />}
        </div>

        <nav className={cn('no-scrollbar flex-1 overflow-y-auto py-1', rail ? 'px-0' : 'px-0')}>
          {favoriteItems.length > 0 && (
            <NavGroup
              id="sevimlilar"
              label="Sevimlilar"
              items={favoriteItems}
              rail={rail}
              collapsed={!rail && collapsedSections.includes('sevimlilar')}
              onToggle={() => toggleSection('sevimlilar')}
              itemProps={itemProps}
            />
          )}
          {sections.map((section) => (
            <NavGroup
              key={section.id}
              id={section.id}
              label={section.label}
              items={section.items}
              rail={rail}
              // Faol sahifa bo'limi yig'ilgan bo'lsa ham ko'rinadi.
              collapsed={!rail && collapsedSections.includes(section.id) && !section.items.some((item) => matchesPath(pathname, item.to, item.end))}
              onToggle={() => toggleSection(section.id)}
              itemProps={itemProps}
            />
          ))}
        </nav>

        <div className={cn('shrink-0 border-t border-border-strong', rail ? 'px-1.5 py-2' : 'px-3 py-2')}>
          {userName && role && (
            <div className={cn('flex items-center gap-2', rail ? 'flex-col' : '')}>
              {!rail && (
                <div className="min-w-0 flex-1 leading-tight">
                  <p className="truncate text-[12.5px] font-semibold text-fg">{userName}</p>
                  <p className="intel-micro truncate">{ROLE_LABEL[role]}</p>
                </div>
              )}
              <IconButton icon={LogOut} label="Tizimdan chiqish" size="sm" variant="danger" onClick={onLogout} />
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

interface NavItemSharedProps {
  pathname: string;
  rail: boolean;
  linkSuffix: string;
  onNavigate: () => void;
  favorites: string[];
  onToggleFavorite: (to: string) => void;
}

/** Bo'lim sarlavhasi: bosh harfli monoshrift yorliq, chiziq va bandlar soni. */
function NavGroup({
  id,
  label,
  items,
  rail,
  collapsed,
  onToggle,
  itemProps,
}: {
  id: string;
  label: string;
  items: NavItem[];
  rail: boolean;
  collapsed: boolean;
  onToggle: () => void;
  itemProps: NavItemSharedProps;
}) {
  const listId = `nav-${id}`;
  const count = String(items.length).padStart(2, '0');
  return (
    <div className="border-b border-border last:border-b-0">
      {rail ? (
        // Yig'ilgan panelda sarlavha o'rniga faqat ajratuvchi chiziq.
        <span className="sr-only" id={listId}>
          {label}
        </span>
      ) : (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-controls={listId}
          className={cn('flex h-7 w-full items-center gap-2 bg-surface-2 px-3 text-left transition-colors hover:bg-surface-3', focusRing)}
        >
          <span className="intel-micro">{label}</span>
          <span className="h-px flex-1 bg-border" aria-hidden="true" />
          <span className="intel-code text-[10px] text-subtle" aria-label={`${items.length} ta band`}>
            {collapsed ? `+${count}` : count}
          </span>
        </button>
      )}
      {!collapsed && (
        <ul id={rail ? undefined : listId} className="flex flex-col py-0.5">
          {items.map((item) => (
            <NavRow key={item.to} item={item} {...itemProps} />
          ))}
        </ul>
      )}
    </div>
  );
}

function NavRow({ item, pathname, rail, linkSuffix, onNavigate, favorites, onToggleFavorite }: NavItemSharedProps & { item: NavItem }) {
  const active = matchesPath(pathname, item.to, item.end);
  const Icon = item.icon;
  const pinned = favorites.includes(item.to);
  return (
    <li className="group/row relative">
      <NavLink
        to={usesViewDate(item.to) ? `${item.to}${linkSuffix}` : item.to}
        end={item.end}
        onClick={onNavigate}
        title={rail ? item.label : undefined}
        aria-label={rail ? item.label : undefined}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'relative flex h-[30px] items-center text-[13px] transition-colors',
          focusRing,
          rail ? 'justify-center px-0' : 'gap-2 pl-3 pr-7',
          // Faol band: to'q ko'k yo'l chizig'i + ko'k matn, to'ldirilgan
          // dumaloq tugma emas.
          active ? 'bg-primary-soft font-semibold text-primary' : 'text-muted hover:bg-surface-2 hover:text-fg',
        )}
      >
        <span className={cn('absolute inset-y-0 left-0 w-[3px]', active ? 'bg-primary' : 'bg-transparent')} aria-hidden="true" />
        {rail ? (
          <Icon size={17} strokeWidth={active ? 2.2 : 1.8} aria-hidden="true" />
        ) : (
          <>
            <Icon size={15} strokeWidth={active ? 2.1 : 1.8} className="shrink-0" aria-hidden="true" />
            <span className="truncate">{item.label}</span>
          </>
        )}
      </NavLink>
      {!rail && (
        <button
          type="button"
          onClick={() => onToggleFavorite(item.to)}
          aria-pressed={pinned}
          aria-label={pinned ? `${item.label}: sevimlilardan olib tashlash` : `${item.label}: sevimlilarga qo'shish`}
          title={pinned ? 'Sevimlilardan olib tashlash' : "Sevimlilarga qo'shish"}
          className={cn(
            'absolute right-0 top-0 flex h-[30px] w-7 items-center justify-center transition-[opacity,color] focus-visible:opacity-100',
            focusRing,
            pinned ? 'text-warning opacity-100' : 'text-subtle opacity-0 hover:text-fg group-hover/row:opacity-100',
          )}
        >
          <Star size={12} fill={pinned ? 'currentColor' : 'none'} aria-hidden="true" />
        </button>
      )}
    </li>
  );
}
