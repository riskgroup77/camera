import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth, type Role } from '../lib/auth';
import { usePermissions, type PermissionKey } from '../lib/permissions';
import { ButtonLink, EmptyState } from '../ui';
import { homeForRole } from './shell/navConfig';

/** Tizimga kirmagan foydalanuvchini /kirish'ga yuboradi (qaytish manzili bilan). */
export function RequireAuth() {
  const { role } = useAuth();
  const location = useLocation();
  if (!role) {
    return <Navigate to="/kirish" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return <Outlet />;
}

function NoAccess({ description }: { description?: ReactNode }) {
  const { role } = useAuth();
  return (
    <EmptyState
      icon={ShieldAlert}
      title="Bu bo'limga kirish huquqingiz yo'q"
      description={
        description ??
        'Bo\'lim faqat tegishli huquqqa ega foydalanuvchilar uchun ochiq. Huquqlarni "Foydalanuvchilar" bo\'limida Super Admin sozlaydi.'
      }
      action={<ButtonLink to={homeForRole(role)}>Bosh sahifaga</ButtonLink>}
    />
  );
}

/** Menyu bu bo'limlarni allaqachon yashiradi; bu himoya to'g'ridan-to'g'ri
 *  havola bilan kirilganda kerak. Haqiqiy chegara baribir backendda. */
export function RequirePermission({ permission, anyOf }: { permission?: PermissionKey; anyOf?: PermissionKey[] }) {
  const { role } = useAuth();
  const { can } = usePermissions();
  // `anyOf` — ro'yxatdagi kamida bittasi yetarli (masalan devor ekrani:
  // viewReports yoki manageAttendance). Ikkalasi berilsa — ikkalasi ham shart.
  const keys = anyOf ?? [];
  const okSingle = permission ? can(permission, role) : true;
  const okAny = keys.length === 0 || keys.some((key) => can(key, role));
  if (!okSingle || !okAny || (!permission && keys.length === 0)) return <NoAccess />;
  return <Outlet />;
}

/** Faqat berilgan rollar (masalan uslub qo'llanmasi — super-admin). */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { role } = useAuth();
  if (!role || !roles.includes(role)) return <NoAccess description="Bu sahifa faqat tizim ma'murlari uchun." />;
  return <Outlet />;
}
