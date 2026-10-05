import {
  BellRing,
  BookUser,
  CalendarRange,
  Clock,
  Cctv,
  ChartColumn,
  Contact,
  DoorOpen,
  FileVideo,
  GraduationCap,
  LayoutDashboard,
  Lock,
  Map as MapIcon,
  MonitorPlay,
  Network,
  ServerCog,
  ShieldCheck,
  Siren,
  Search,
  UserCheck,
  type LucideIcon,
} from 'lucide-react';
import type { Role } from '../../lib/auth';
import type { PermissionKey } from '../../lib/permissions';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Menyudagi qisqa indeks kodi — yig'ilgan panelda va qidiruvda
   *  bandni raqamlab turadi (texnik ko'rsatkich kabi, uch harf). */
  code: string;
  permission?: PermissionKey;
  /** Shulardan biri yetarli (backend ham shunday: o'qish endpointlari bir nechta huquqni qabul qiladi). */
  anyOf?: PermissionKey[];
  /** Faqat aniq manzil (masalan "/" — boshqa hamma manzilning boshi). */
  end?: boolean;
}

export interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: 'monitoring',
    label: 'Monitoring',
    items: [
      { to: '/', code: 'HOL', label: 'Nazorat', icon: LayoutDashboard, end: true },
      { to: '/videodevor', code: 'KAM', label: 'Jonli kameralar', icon: MonitorPlay, permission: 'viewLive' },
      { to: '/xarita', code: 'XAR', label: 'Xarita', icon: MapIcon, permission: 'viewLive' },
      { to: '/shaxs-qidirish', code: 'QID', label: 'Shaxs qidirish', icon: Search, permission: 'viewLive' },
      { to: '/hodisalar', code: 'HOD', label: 'Hodisalar', icon: Siren, permission: 'reviewEvents' },
      { to: '/tekshiruv', code: 'TEK', label: 'Tekshiruv', icon: UserCheck, permission: 'reviewEvents' },
    ],
  },
  {
    id: 'davomat',
    label: 'Davomat',
    items: [
      { to: '/talabalar', code: 'TLB', label: 'Talabalar', icon: GraduationCap, anyOf: ['manageAttendance', 'viewReports'] },
      { to: '/oqituvchilar', code: 'XOD', label: 'Xodimlar', icon: BookUser, anyOf: ['manageAttendance', 'viewReports'] },
      { to: '/dars-jadvali', code: 'DRS', label: 'Dars jadvali', icon: CalendarRange, anyOf: ['manageAttendance', 'viewReports', 'manageLessons'] },
      { to: '/turniketlar', code: 'TRN', label: 'Turniketlar', icon: DoorOpen, permission: 'manageIntegrations' },
    ],
  },
  {
    id: 'tahlil',
    label: 'Tahlil',
    items: [
      { to: '/kunlik-tahlil', code: 'KTH', label: 'Kunlik tahlil', icon: FileVideo, anyOf: ['viewReports', 'manageAttendance', 'systemSettings'] },
      { to: '/hisobotlar', code: 'HIS', label: 'Hisobotlar', icon: ChartColumn, permission: 'viewReports' },
    ],
  },
  {
    id: 'malumotlar',
    label: "Ma'lumotlar",
    items: [
      { to: '/reestr', code: 'RST', label: 'Shaxslar reestri', icon: Contact, permission: 'registerPeople' },
      // Ruxsatsiz: o'qish hammaga ochiq, o'zgartirish tugmalari sahifaning
      // o'zida manageOrgStructure bo'yicha yashiriladi.
      { to: '/tuzilma', code: 'TUZ', label: 'Tashkiliy tuzilma', icon: Network },
    ],
  },
  {
    id: 'sozlamalar',
    label: 'Sozlamalar',
    items: [
      { to: '/sozlamalar/kameralar', code: 'SKM', label: 'Kameralar', icon: Cctv, permission: 'editCameraLocation' },
      { to: '/sozlamalar/ish-vaqti', code: 'SIV', label: 'Ish vaqti', icon: Clock, permission: 'manageAttendance' },
      { to: '/sozlamalar/bildirishnomalar', code: 'SBL', label: 'Bildirishnomalar', icon: BellRing, permission: 'manageNotifications' },
      { to: '/sozlamalar/foydalanuvchilar', code: 'SFD', label: 'Foydalanuvchilar', icon: ShieldCheck, permission: 'manageRoles' },
      { to: '/sozlamalar/tizim', code: 'STZ', label: 'Tizim holati', icon: ServerCog, permission: 'systemSettings' },
      { to: '/sozlamalar/maxfiylik', code: 'SMX', label: 'Maxfiylik', icon: Lock, permission: 'managePrivacy' },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

/** Ayrim rollar butun panelni emas, sanoqli sahifani ko'radi.
 *
 * Huquqlar matritsasi "nima qilish mumkin"ni boshqaradi, bu ro'yxat esa
 * "qayerga kirish mumkin"ni: kamera mas'uli uchun qolgan bo'limlar
 * (davomat, hodisalar, hisobotlar) shunchaki keraksiz va chalg'ituvchi.
 * Haqiqiy chegara baribir backendda — bu ro'yxat menyuni tozalaydi. */
export const ROLE_PAGES: Partial<Record<Role, string[]>> = {
  'kamera-masuli': ['/tuzilma', '/sozlamalar/kameralar'],
};

/** Cheklangan rol kirgandan keyin qayerga tushadi (kunlik ish — kameralar). */
export const ROLE_HOME: Partial<Record<Role, string>> = {
  'kamera-masuli': '/sozlamalar/kameralar',
};

export const ROLE_LABEL: Record<Role, string> = {
  'super-admin': 'Super Admin',
  admin: 'Admin',
  'kamera-masuli': "Kamera mas'uli",
};

/** `pathname` shu bo'lim ichidami ("/talabalar/guruh/x" → "/talabalar"). */
export function matchesPath(pathname: string, to: string, end = false): boolean {
  if (to === '/') return pathname === '/';
  if (end) return pathname === to;
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function homeForRole(role: Role | null | undefined): string {
  return (role && ROLE_HOME[role]) || '/';
}

/** Cheklangan rol uchun manzil ruxsat etilganmi (cheklanmagan rol — doim ha). */
export function isPathAllowedForRole(role: Role | null | undefined, pathname: string): boolean {
  const allowed = role ? ROLE_PAGES[role] : undefined;
  if (!allowed) return true;
  return allowed.some((to) => matchesPath(pathname, to));
}

/** Menyu: huquq va rol bo'yicha filtrlangan, bo'sh bo'limlarsiz. */
export function visibleSections(can: (key: PermissionKey) => boolean, role: Role | null | undefined): NavSection[] {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) =>
        (!item.permission || can(item.permission)) &&
        (!item.anyOf || item.anyOf.some((key) => can(key))) &&
        isPathAllowedForRole(role, item.to),
    ),
  })).filter((section) => section.items.length > 0);
}

/** Joriy manzilga mos menyu bandi va bo'limi (eng uzun moslik). */
export function findActive(pathname: string): { section: NavSection; item: NavItem } | null {
  let best: { section: NavSection; item: NavItem } | null = null;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (matchesPath(pathname, item.to, item.end) && (!best || item.to.length > best.item.to.length)) {
        best = { section, item };
      }
    }
  }
  return best;
}

/** Global sana tanlagichi ko'rinadigan (davomat) sahifalar. */
// /shaxs — o'z davr tanlagichi bor (global sana u yerda ishlamaydi).
const DATE_ROUTES = ['/', '/talabalar', '/oqituvchilar'];

export function usesViewDate(pathname: string): boolean {
  return DATE_ROUTES.some((to) => matchesPath(pathname, to));
}

/** Devor ekrani — o'z sahifasi (taqdimot rejimidan farqli). */
export const WALL_SCREEN_PATH = '/markaz-ekran';

/** Devor ekranini alohida oynada ochadi. */
export function openWallScreen() {
  window.open(WALL_SCREEN_PATH, 'markaz-ekran', 'noopener');
}
