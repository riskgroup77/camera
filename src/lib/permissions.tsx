import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from './apiClient';
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
  | 'exportData';

export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  manageCameras: "Kameralarni qo'shish va o'chirish",
  configureAi: 'AI Kriteriyalarini sozlash',
  registerPeople: "Talaba/Xodimlarni ro'yxatdan o'tkazish",
  systemSettings: 'Tizim sozlamalari va Audit',
  viewReports: "Hisobotlarni ko'rish",
  viewLive: "Kamera tasvirini real vaqtda ko'rish",
  manageRoles: 'Foydalanuvchi rollarini boshqarish',
  exportData: "Ma'lumotlarni eksport qilish",
};

export type PermissionMatrix = Record<PermissionKey, { superAdmin: boolean; admin: boolean }>;

export const DEFAULT_PERMISSIONS: PermissionMatrix = {
  manageCameras: { superAdmin: true, admin: true },
  configureAi: { superAdmin: true, admin: true },
  registerPeople: { superAdmin: true, admin: true },
  systemSettings: { superAdmin: true, admin: false },
  viewReports: { superAdmin: true, admin: true },
  viewLive: { superAdmin: true, admin: true },
  manageRoles: { superAdmin: true, admin: false },
  exportData: { superAdmin: true, admin: false },
};

const STORAGE_KEY = 'camera-permissions';

interface PermissionsContextValue {
  matrix: PermissionMatrix;
  can: (key: PermissionKey, role: Role | null) => boolean;
  toggle: (key: PermissionKey, role: 'superAdmin' | 'admin') => void;
}

const PermissionsContext = createContext<PermissionsContextValue | null>(null);

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

  useEffect(() => {
    if (!isBackendConfigured || !token) return;
    let cancelled = false;
    api
      .get<PermissionMatrix>('/api/permissions', token)
      .then((res) => {
        if (!cancelled) setRemoteMatrix(res);
      })
      .catch(() => {
        /* ulanish muvaffaqiyatsiz — standart matritsa bilan davom etamiz */
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const matrix = isBackendConfigured ? remoteMatrix : localMatrix;

  function can(key: PermissionKey, role: Role | null): boolean {
    if (!role) return false;
    return role === 'super-admin' ? matrix[key].superAdmin : matrix[key].admin;
  }

  function toggle(key: PermissionKey, role: 'superAdmin' | 'admin') {
    if (!isBackendConfigured) {
      setLocalMatrix((prev) => ({
        ...prev,
        [key]: { ...prev[key], [role]: !prev[key][role] },
      }));
      return;
    }
    if (!token) return;

    setRemoteMatrix((prev) => ({
      ...prev,
      [key]: { ...prev[key], [role]: !prev[key][role] },
    }));

    api
      .patch<{ superAdmin: boolean; admin: boolean }>(`/api/permissions/${key}`, { role }, token)
      .then((updated) => {
        setRemoteMatrix((prev) => ({ ...prev, [key]: updated }));
      })
      .catch(() => {
        // Server rad etdi (masalan, huquq yo'q) — optimistik o'zgarishni qaytaramiz.
        setRemoteMatrix((prev) => ({
          ...prev,
          [key]: { ...prev[key], [role]: !prev[key][role] },
        }));
      });
  }

  return (
    <PermissionsContext.Provider value={{ matrix, can, toggle }}>{children}</PermissionsContext.Provider>
  );
}

export function usePermissions() {
  const ctx = useContext(PermissionsContext);
  if (!ctx) throw new Error('usePermissions must be used within PermissionsProvider');
  return ctx;
}
