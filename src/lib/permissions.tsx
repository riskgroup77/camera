import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, api } from './apiClient';
import { useAuth, type Role } from './auth';
import { isBackendConfigured } from './config';
import { usePersistedState } from './usePersistedState';

export type PermissionKey =
  | 'manageCameras'
  | 'configureAi'
  | 'registerPeople'
  | 'systemSettings'
  | 'viewReports'
  | 'viewLive'
  | 'manageRoles'
  | 'exportData'
  | 'editCameraLocation'
  | 'reviewEvents'
  | 'deleteEvents'
  | 'manageAttendance'
  | 'manageOrgStructure'
  | 'manageLessons'
  | 'manageNotifications'
  | 'manageIntegrations'
  | 'controlPtz'
  | 'managePrivacy';

export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  manageCameras: "Kameralarni qo'shish va o'chirish",
  configureAi: 'AI Kriteriyalarini sozlash',
  registerPeople: "Talaba/Xodimlarni ro'yxatdan o'tkazish",
  systemSettings: 'Tizim sozlamalari va Audit',
  viewReports: "Hisobotlarni ko'rish",
  viewLive: "Kamera tasvirini real vaqtda ko'rish",
  manageRoles: 'Foydalanuvchi rollarini boshqarish',
  exportData: "Ma'lumotlarni eksport qilish",
  editCameraLocation: "Kamera joylashuvini to'g'rilash (bino, qavat, zona)",
  reviewEvents: "Hodisalar jurnalini ko'rish va ko'rib chiqish",
  deleteEvents: "Hodisani butunlay o'chirish",
  manageAttendance: "Davomat va o'qituvchilar kuzatuvini ko'rish, davomatni tuzatish",
  manageOrgStructure: "Tashkiliy tuzilma: binolar va kafedra–bino bog'lanishi",
  manageLessons: 'Dars jadvali (HEMIS) va darsdagi davomat',
  manageNotifications: 'Bildirishnomalar (Telegram, SMS) sozlash',
  manageIntegrations: 'Integratsiyalar (HEMIS, turniket)',
  controlPtz: 'PTZ kamerani boshqarish (burish, yaqinlashtirish)',
  managePrivacy: "Maxfiylik: rozilik, ma'lumotni eksport va o'chirish",
};

export type PermissionMatrix = Record<
  PermissionKey,
  { superAdmin: boolean; admin: boolean; cameraSteward: boolean }
>;

/** Matritsadagi ustun nomi — JWT'dagi rol emas. */
export type PermissionRoleColumn = 'superAdmin' | 'admin' | 'cameraSteward';

export const DEFAULT_PERMISSIONS: PermissionMatrix = {
  manageCameras: { superAdmin: true, admin: true, cameraSteward: false },
  configureAi: { superAdmin: true, admin: true, cameraSteward: false },
  registerPeople: { superAdmin: true, admin: true, cameraSteward: false },
  systemSettings: { superAdmin: true, admin: false, cameraSteward: false },
  viewReports: { superAdmin: true, admin: true, cameraSteward: false },
  viewLive: { superAdmin: true, admin: true, cameraSteward: false },
  manageRoles: { superAdmin: true, admin: false, cameraSteward: false },
  exportData: { superAdmin: true, admin: false, cameraSteward: false },
  editCameraLocation: { superAdmin: true, admin: true, cameraSteward: true },
  // Backenddagi app/seed.py va alembic n7b8c9d0e1f2 bilan bir xil.
  reviewEvents: { superAdmin: true, admin: true, cameraSteward: false },
  // Hodisa — dalil: admin uni tasdiqlaydi yoki rad etadi, o'chirmaydi.
  deleteEvents: { superAdmin: true, admin: false, cameraSteward: false },
  manageAttendance: { superAdmin: true, admin: true, cameraSteward: false },
  manageOrgStructure: { superAdmin: true, admin: true, cameraSteward: false },
  manageLessons: { superAdmin: true, admin: true, cameraSteward: false },
  // Backenddagi app/seed.py va alembic s1a2b3c4d5e6 bilan bir xil.
  manageNotifications: { superAdmin: true, admin: true, cameraSteward: false },
  manageIntegrations: { superAdmin: true, admin: false, cameraSteward: false },
  controlPtz: { superAdmin: true, admin: true, cameraSteward: false },
  managePrivacy: { superAdmin: true, admin: false, cameraSteward: false },
};

/** Rol qaysi ustundan o'qiladi — backenddagi _PERMISSION_COLUMN bilan bir xil. */
const ROLE_COLUMN: Record<Role, PermissionRoleColumn> = {
  'super-admin': 'superAdmin',
  admin: 'admin',
  'kamera-masuli': 'cameraSteward',
};

/** "Rol" tanlagichidagi variantlar (AdminUser.role yorliqlari). */
export const ROLE_OPTIONS = [
  { value: 'Super Admin', label: 'Super Admin' },
  { value: 'Admin', label: 'Admin' },
  { value: "Kamera mas'uli", label: "Kamera mas'uli" },
];

/**
 * Backend (app/routers/users.py: _resolve_role) "Super Admin" rolini faqat
 * Super Admin'ga berishga ruxsat beradi. `manageRoles` sozlanadigan huquq
 * bo'lgani uchun oddiy admin ham foydalanuvchi oynasiga tusha oladi — unga
 * o'sha variantni KO'RSATIB, keyin 403 qaytarish o'rniga ro'yxatdan olib
 * tashlaymiz (UI hech qachon server rad etadigan tugmani ko'rsatmasin).
 */
export function roleOptionsFor(myRole: Role | null) {
  return myRole === 'super-admin' ? ROLE_OPTIONS : ROLE_OPTIONS.filter((o) => o.value !== 'Super Admin');
}

const STORAGE_KEY = 'camera-permissions';

interface PermissionsContextValue {
  matrix: PermissionMatrix;
  can: (key: PermissionKey, role: Role | null) => boolean;
  toggle: (key: PermissionKey, role: PermissionRoleColumn) => void;
  /** Oxirgi `toggle` serverda rad etilgan bo'lsa — sababi. Ilgari xato
   *  jimgina yutilardi: kalit o'z holiga qaytardi-yu, foydalanuvchi
   *  "bosdim, lekin hech nima bo'lmadi" deb qolaverardi. */
  saveError: string | null;
  clearSaveError: () => void;
}

const PermissionsContext = createContext<PermissionsContextValue | null>(null);

/** /api/permissions yuklanmasa — qayta urinish oraliqlari. */
const PERMISSION_RETRY_MS = [2000, 5000, 15000, 30000];

/**
 * Backend ulangan bo'lsa huquqlar matritsasi GET /api/permissions'dan olinadi
 * va tahrirlash PATCH /api/permissions/{key} orqali serverga yoziladi — bu
 * yerdagi tekshiruv faqat UX (navigatsiya/tugmalarni yashirish) uchun, haqiqiy
 * xavfsizlik chegarasi backendning require_permission()'ida. Backend
 * ulanmagan bo'lsa (demo rejim) localStorage'dagi eski xatti-harakat saqlanadi.
 */
export function PermissionsProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [localMatrix, setLocalMatrix] = usePersistedState<PermissionMatrix>(STORAGE_KEY, DEFAULT_PERMISSIONS);
  const [remoteMatrix, setRemoteMatrix] = useState<PermissionMatrix>(DEFAULT_PERMISSIONS);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!isBackendConfigured || !token) return;
    let cancelled = false;
    let timer: number | undefined;
    let attempt = 0;
    // Bir martalik xato (timeout, qisqa uzilish) ilgari sahifa qayta
    // yuklanguncha STANDART matritsani qoldirardi: sozlangan huquqlar
    // o'rniga keraksiz tugmalar (403) ko'rinardi yoki kerakli bo'limlar
    // yo'qolardi. Endi — kechikish bilan qayta urinish va oynaga qaytganda
    // yangilash (Super Admin matritsani o'zgartirgan bo'lishi mumkin).
    const load = () => {
      window.clearTimeout(timer);
      api
        .get<PermissionMatrix>('/api/permissions', token)
        .then((res) => {
          if (cancelled) return;
          attempt = 0;
          setRemoteMatrix(res);
        })
        .catch(() => {
          if (cancelled) return;
          const delay = PERMISSION_RETRY_MS[Math.min(attempt, PERMISSION_RETRY_MS.length - 1)];
          attempt += 1;
          timer = window.setTimeout(load, delay);
        });
    };
    load();
    const onFocus = () => load();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [token]);

  // Demo rejimda brauzerda eski (yangi kalitlarsiz) matritsa saqlangan
  // bo'lishi mumkin — yetishmagan kalitlar standartdan olinadi. Server
  // rejimida bunday to'ldirish YO'Q: server bilmagan kalitni server
  // baribir rad etadi, UI esa uni ochiq ko'rsatmasligi kerak.
  const matrix = isBackendConfigured ? remoteMatrix : { ...DEFAULT_PERMISSIONS, ...localMatrix };

  function can(key: PermissionKey, role: Role | null): boolean {
    if (!role) return false;
    // Server yangi huquq kalitini bilmasligi mumkin (eski backend) —
    // bunday holda taqiqlaymiz, ochib qo'ymaymiz.
    return matrix[key]?.[ROLE_COLUMN[role]] ?? false;
  }

  function toggle(key: PermissionKey, role: PermissionRoleColumn) {
    if (!isBackendConfigured) {
      setLocalMatrix((prev) => {
        const row = prev[key] ?? DEFAULT_PERMISSIONS[key];
        return { ...prev, [key]: { ...row, [role]: !row[role] } };
      });
      return;
    }
    if (!token) return;

    setSaveError(null);
    setRemoteMatrix((prev) => ({
      ...prev,
      [key]: { ...prev[key], [role]: !prev[key][role] },
    }));

    api
      .patch<PermissionMatrix[PermissionKey]>(`/api/permissions/${key}`, { role }, token)
      .then((updated) => {
        setRemoteMatrix((prev) => ({ ...prev, [key]: updated }));
      })
      .catch((err: unknown) => {
        // Server rad etdi (masalan, huquq yo'q) — optimistik o'zgarishni
        // qaytaramiz VA sababini ko'rsatamiz.
        setRemoteMatrix((prev) => ({
          ...prev,
          [key]: { ...prev[key], [role]: !prev[key][role] },
        }));
        setSaveError(
          err instanceof ApiError
            ? `«${PERMISSION_LABELS[key]}» saqlanmadi: ${err.message}`
            : `«${PERMISSION_LABELS[key]}» saqlanmadi — server bilan bog'lanib bo'lmadi`,
        );
      });
  }

  return (
    <PermissionsContext.Provider value={{ matrix, can, toggle, saveError, clearSaveError: () => setSaveError(null) }}>
      {children}
    </PermissionsContext.Provider>
  );
}

export function usePermissions() {
  const ctx = useContext(PermissionsContext);
  if (!ctx) throw new Error('usePermissions must be used within PermissionsProvider');
  return ctx;
}
