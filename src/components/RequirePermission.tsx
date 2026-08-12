import { Outlet } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { usePermissions, type PermissionKey } from '../lib/permissions';

export default function RequirePermission({ permission }: { permission: PermissionKey }) {
  const { role } = useAuth();
  const { can } = usePermissions();

  if (!can(permission, role)) {
    return (
      <div className="glass flex flex-col items-center gap-3 p-10 text-center">
        <ShieldAlert size={32} className="text-amber-500" />
        <p className="text-sm font-bold text-slate-800 dark:text-slate-200">
          Sizda bu bo'limga kirish huquqi yo'q
        </p>
        <p className="max-w-sm text-xs text-slate-500 dark:text-slate-400">
          Ushbu bo'lim faqat tegishli huquqqa ega foydalanuvchilar uchun ochiq.
          Huquqlarni "Foydalanuvchilar va Rollar" bo'limida Super Admin sozlashi mumkin.
        </p>
      </div>
    );
  }

  return <Outlet />;
}
