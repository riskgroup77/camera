import { useState } from 'react';
import { Check, Info, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import ConfirmDialog from '../../components/ConfirmDialog';
import AddUserModal from '../../components/admin/AddUserModal';
import EditUserModal from '../../components/admin/EditUserModal';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useServerPage } from '../../lib/useServerPage';
import { PERMISSION_LABELS, usePermissions, type PermissionKey } from '../../lib/permissions';
import type { AdminUser } from '../../types';

const PERMISSION_KEYS = Object.keys(PERMISSION_LABELS) as PermissionKey[];

export default function UsersRolesPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const { role: myRole, token } = useAuth();
  const { matrix, toggle } = usePermissions();
  const {
    items: users,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
    reload,
  } = useServerPage<AdminUser>('/api/users', {}, 9);

  const canEdit = myRole === 'super-admin';

  async function handleDelete() {
    if (!deleting) return;
    await api.del(`/api/users/${deleting.id}`, token);
    setDeleting(null);
    reload();
  }

  return (
    <div className="space-y-4">
      <section className="glass p-6">
        <PageHeader
          title="Foydalanuvchilar va Rollar"
          subtitle="Foydalanuvchi rollari va huquqlari boshqaruvi"
          action={
            <button
              onClick={() => setModalOpen(true)}
              className="btn-glass flex items-center gap-1.5 !bg-indigo-600 !text-white hover:!bg-indigo-700"
            >
              <Plus size={14} />
              Yangi foydalanuvchi qo'shish
            </button>
          }
        />

        <h3 className="mb-3 text-sm font-bold text-slate-700 dark:text-slate-300">Faol foydalanuvchilar</h3>
        {error && (
          <p className="mb-3 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
            {error}
          </p>
        )}
        {loading && users.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-slate-400">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {users.map((u) => (
              <div key={u.id} className="glass-deep flex items-center gap-3 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-100 dark:bg-indigo-500/15 text-xs font-bold text-indigo-600">
                  {u.initials}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">{u.name}</p>
                  <p className="truncate text-xs text-slate-500 dark:text-slate-400">Oxirgi kirish: {u.lastLogin}</p>
                </div>
                <Badge tone={u.role === 'Super Admin' ? 'indigo' : 'slate'}>{u.role}</Badge>
                <button
                  onClick={() => setEditing(u)}
                  title="Tahrirlash"
                  className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/60 hover:text-indigo-600 dark:text-slate-500 dark:hover:bg-white/10 dark:hover:text-indigo-400"
                >
                  <Pencil size={14} />
                </button>
                <button
                  onClick={() => setDeleting(u)}
                  title="O'chirish"
                  className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/60 hover:text-red-600 dark:text-slate-500 dark:hover:bg-white/10 dark:hover:text-red-400"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
      </section>

      <AddUserModal open={modalOpen} onClose={() => setModalOpen(false)} onAdd={() => reload()} />
      <EditUserModal user={editing} onClose={() => setEditing(null)} onSave={() => reload()} />
      <ConfirmDialog
        open={!!deleting}
        title="Foydalanuvchini o'chirish"
        message={deleting ? `"${deleting.name}" (${deleting.login}) foydalanuvchisini o'chirishni tasdiqlaysizmi? Bu amalni ortga qaytarib bo'lmaydi.` : ''}
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />

      <section className="glass p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-700 dark:text-slate-300">Huquqlar matritsasi</h3>
          {!canEdit && (
            <span className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
              <Info size={13} />
              Faqat Super Admin tahrirlashi mumkin
            </span>
          )}
        </div>
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <th className="px-4 py-3">Huquq / Ruxsat</th>
                <th className="px-4 py-3 text-center">Super Admin</th>
                <th className="px-4 py-3 text-center">Admin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {PERMISSION_KEYS.map((key) => (
                <tr key={key} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-200">
                    {PERMISSION_LABELS[key]}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <PermissionMark granted={matrix[key].superAdmin} locked />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <PermissionMark
                      granted={matrix[key].admin}
                      onToggle={canEdit ? () => toggle(key, 'admin') : undefined}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] text-slate-400 dark:text-slate-500">
          Bu yerdagi sozlamalar navigatsiya menyusi va eksport tugmalarini haqiqatda
          cheklaydi — "Admin" sifatida kirsangiz, o'chirilgan bo'limlar sidebar'da
          ko'rinmaydi.
        </p>
      </section>
    </div>
  );
}

function PermissionMark({
  granted,
  locked,
  onToggle,
}: {
  granted: boolean;
  locked?: boolean;
  onToggle?: () => void;
}) {
  const icon = granted ? (
    <Check size={16} className="text-emerald-600 dark:text-emerald-400" />
  ) : (
    <X size={16} className="text-red-400" />
  );

  if (!onToggle || locked) {
    return <span className="mx-auto flex h-6 w-6 items-center justify-center">{icon}</span>;
  }

  return (
    <button
      onClick={onToggle}
      title="Bosib o'zgartiring"
      className="mx-auto flex h-6 w-6 items-center justify-center rounded-md transition-colors hover:bg-white/60 dark:hover:bg-white/10"
    >
      {icon}
    </button>
  );
}
