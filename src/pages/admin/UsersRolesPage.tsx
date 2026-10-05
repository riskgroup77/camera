import { useMemo, useState } from 'react';
import { Building2, Check, KeyRound, Lock, Pencil, Plus, ShieldOff, Trash2, UserPlus, Users, X } from 'lucide-react';
import {
  Avatar,
  Badge,
  Button,
  CodeText,
  ConfirmDialog,
  DataTable,
  FilterBar,
  IconButton,
  IntelPanel,
  MicroLabel,
  Page,
  cn,
  useToast,
  useUrlTab,
  type DataTableColumn,
  type TabItem,
  type Tone,
} from '../../ui';
import AddUserModal from '../../components/admin/AddUserModal';
import EditUserModal from '../../components/admin/EditUserModal';
import UserBuildingScopeModal from '../../components/admin/UserBuildingScopeModal';
import { Notice, Switch, pagerFooter } from '../../components/settings/kit';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { invalidateServerPageCache, useServerPage } from '../../lib/useServerPage';
import { PERMISSION_LABELS, usePermissions, type PermissionKey } from '../../lib/permissions';
import type { AdminUser } from '../../types';

const PERMISSION_KEYS = Object.keys(PERMISSION_LABELS) as PermissionKey[];
const PAGE_SIZE = 9;

const ROLE_TONE: Record<AdminUser['role'], Tone> = {
  'Super Admin': 'primary',
  Admin: 'info',
  "Kamera mas'uli": 'neutral',
};

type TabId = 'foydalanuvchilar' | 'huquqlar';

/** Ustun sarlavhasi — bosh harfli mikro-yorliq. */
function ColumnHead({ label }: { label: string }) {
  return <MicroLabel className="!text-fg">{label}</MicroLabel>;
}

export default function UsersRolesPage() {
  const toast = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const [resetting2fa, setResetting2fa] = useState<AdminUser | null>(null);
  const [scoping, setScoping] = useState<AdminUser | null>(null);
  const { role: myRole, token, userName } = useAuth();
  const { matrix, toggle, saveError, clearSaveError } = usePermissions();
  // Serverga ketayotgan huquq o'zgarishlari. PATCH /api/permissions/{key}
  // — "teskarisiga o'zgartir" buyrug'i, shuning uchun ikki marta tez
  // bosilsa ikki marta aylanib, natija boshlang'ich holatga qaytardi.
  const [pendingPermissions, setPendingPermissions] = useState<PermissionKey[]>([]);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [riskFilter, setRiskFilter] = useState('');
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
  } = useServerPage<AdminUser>('/api/users', { search: search.trim() || undefined, role: roleFilter || undefined, xavf: riskFilter || undefined }, PAGE_SIZE);

  const canEdit = myRole === 'super-admin';

  const tabs = useMemo<TabItem<TabId>[]>(
    () => [
      { id: 'foydalanuvchilar', label: 'Foydalanuvchilar', icon: Users, count: loading && users.length === 0 ? null : total },
      { id: 'huquqlar', label: 'Huquqlar matritsasi', icon: KeyRound },
    ],
    [loading, users.length, total],
  );
  const [tab] = useUrlTab(tabs);

  function refresh() {
    invalidateServerPageCache('/api/users');
    reload();
  }

  /** Server (app/routers/users.py) rad etadigan o'chirishlar — sababi bilan.
   *  Hisob egasi `userName` orqali taxmin qilinadi: aniq tekshiruv baribir
   *  serverda, bu faqat behuda bosishning oldini oladi. */
  function deleteBlockReason(user: AdminUser): string | null {
    if (userName && user.name === userName) return "O'zingizni o'chira olmaysiz";
    if (user.role === 'Super Admin' && myRole !== 'super-admin') {
      return "Faqat Super Admin o'chira oladi";
    }
    return null;
  }

  async function handleDelete() {
    if (!deleting) return;
    // Xato bo'lsa ConfirmDialog o'zi ko'rsatadi va yopilmaydi.
    await api.del(`/api/users/${deleting.id}`, token);
    toast.success(`${deleting.name} o'chirildi`);
    setDeleting(null);
    refresh();
  }

  async function handleReset2fa() {
    if (!resetting2fa) return;
    await api.post(`/api/users/${resetting2fa.id}/2fa/bekor`, undefined, token);
    toast.success(`${resetting2fa.name} — ikki bosqichli kirish bekor qilindi`);
    setResetting2fa(null);
    refresh();
  }

  const userColumns: DataTableColumn<AdminUser>[] = [
    {
      key: 'name',
      header: 'Foydalanuvchi',
      sortValue: (u) => u.name,
      cell: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={u.name} size="sm" />
          <div className="min-w-0">
            <p className="truncate font-medium text-fg">{u.name}</p>
            <CodeText className="block truncate text-[11px] text-muted">{u.login}</CodeText>
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Rol',
      sortValue: (u) => u.role,
      cell: (u) => (
        <Badge tone={ROLE_TONE[u.role] ?? 'neutral'} dot>
          {u.role}
        </Badge>
      ),
    },
    {
      key: 'contact',
      header: 'Aloqa',
      hideOnMobile: true,
      cell: (u) =>
        u.email || u.phone || u.telegramLinked ? (
          <div className="min-w-0 text-[13px]">
            {u.email && <p className="truncate text-fg">{u.email}</p>}
            <p className="flex flex-wrap items-center gap-1.5 text-muted">
              {u.phone && <CodeText className="text-[12px]">{u.phone}</CodeText>}
              {u.telegramLinked && (
                <Badge tone="success" size="sm">
                  Telegram
                </Badge>
              )}
            </p>
          </div>
        ) : (
          <span className="text-subtle">—</span>
        ),
    },
    {
      key: 'security',
      header: 'Kirish',
      hideOnMobile: true,
      cell: (u) => {
        const scope = u.allowedBuildingIds?.length ?? 0;
        return (
          <div className="flex flex-wrap items-center gap-1.5">
            {u.twoFactorEnabled ? (
              <Badge tone="success" size="sm">
                2FA
              </Badge>
            ) : (
              // Administrator hisobi faqat parol bilan — eng katta xavf.
              <Badge tone={u.role === 'Super Admin' || u.role === 'Admin' ? 'danger' : 'neutral'} size="sm">
                Faqat parol
              </Badge>
            )}
            {u.role !== 'Super Admin' && scope > 0 && (
              <Badge tone="warning" size="sm">
                {scope} ta bino
              </Badge>
            )}
          </div>
        );
      },
    },
    {
      key: 'lastLogin',
      header: 'Oxirgi kirish',
      sortValue: (u) => u.lastLogin,
      mono: true,
      cell: (u) => (
        <span className="flex flex-col gap-0.5">
          <CodeText className="whitespace-nowrap text-[12px] text-muted">{u.lastLogin}</CodeText>
          {u.lastLoginDays != null && u.lastLoginDays >= 90 && (
            <Badge tone="warning" size="sm">{`${u.lastLoginDays} kun kirmagan`}</Badge>
          )}
        </span>
      ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">Amallar</span>,
      align: 'right',
      width: '9rem',
      mobileLabel: 'Amallar',
      cell: (u) => {
        const blocked = deleteBlockReason(u);
        return (
          <div onClick={(e) => e.stopPropagation()} className="flex justify-end gap-1">
            <IconButton icon={Pencil} label={`${u.name} — tahrirlash`} size="sm" onClick={() => setEditing(u)} />
            {/* Super Admin doim barcha binolarni ko'radi (server ham rad etadi). */}
            {u.role !== 'Super Admin' && (
              <IconButton icon={Building2} label={`${u.name} — bino doirasi`} size="sm" onClick={() => setScoping(u)} />
            )}
            {u.twoFactorEnabled && (
              <IconButton
                icon={ShieldOff}
                label={`${u.name} — ikki bosqichli kirishni bekor qilish`}
                size="sm"
                onClick={() => setResetting2fa(u)}
              />
            )}
            {/* Server rad etadigan tugma bosiladigan holda turmasin —
                sababi tooltipda va ekran o'quvchi uchun yorliqda. */}
            <IconButton
              icon={Trash2}
              label={blocked ? `${u.name} — o'chirib bo'lmaydi: ${blocked}` : `${u.name} — o'chirish`}
              title={blocked ?? undefined}
              size="sm"
              variant="danger"
              disabled={Boolean(blocked)}
              onClick={() => setDeleting(u)}
            />
          </div>
        );
      },
    },
  ];

  const permissionKeys = PERMISSION_KEYS.filter((key) => matrix[key]);

  /** Bir kalit bo'yicha bir vaqtda bitta so'rov — tez ikki bosish
   *  serverdagi qiymatni ikki marta aylantirib qo'ymasin. */
  function togglePermission(key: PermissionKey, column: 'admin' | 'cameraSteward') {
    if (pendingPermissions.includes(key)) return;
    setPendingPermissions((prev) => [...prev, key]);
    toggle(key, column);
    // `toggle` promise qaytarmaydi (lib/permissions.tsx) — optimistik
    // qiymat darhol yangilanadi, javob esa keyin keladi. Qisqa qulf
    // qo'sh bosishni to'xtatish uchun yetarli.
    window.setTimeout(() => setPendingPermissions((prev) => prev.filter((k) => k !== key)), 600);
  }

  const permissionColumns: DataTableColumn<PermissionKey>[] = [
    {
      key: 'permission',
      header: <ColumnHead label="Huquq" />,
      sortValue: (key) => PERMISSION_LABELS[key],
      cell: (key) => <span className="block min-w-0 text-[13px] font-medium text-fg">{PERMISSION_LABELS[key]}</span>,
    },
    {
      key: 'superAdmin',
      header: <ColumnHead label="Super Admin" />,
      align: 'center',
      width: '9rem',
      cell: (key) => (
        <PermissionMark
          granted={matrix[key].superAdmin}
          lockedReason="Super Admin huquqlari o'zgarmaydi"
          label={`${PERMISSION_LABELS[key]} — Super Admin`}
        />
      ),
    },
    {
      key: 'admin',
      header: <ColumnHead label="Admin" />,
      align: 'center',
      width: '9rem',
      cell: (key) => (
        <PermissionMark
          granted={matrix[key].admin}
          label={`${PERMISSION_LABELS[key]} — Admin`}
          busy={pendingPermissions.includes(key)}
          onToggle={canEdit ? () => togglePermission(key, 'admin') : undefined}
        />
      ),
    },
    {
      key: 'cameraSteward',
      header: <ColumnHead label="Kamera mas'uli" />,
      align: 'center',
      width: '9rem',
      cell: (key) => (
        <PermissionMark
          granted={matrix[key].cameraSteward}
          label={`${PERMISSION_LABELS[key]} — Kamera mas'uli`}
          busy={pendingPermissions.includes(key)}
          onToggle={canEdit ? () => togglePermission(key, 'cameraSteward') : undefined}
        />
      ),
    },
  ];

  return (
    <Page
      title="Foydalanuvchilar"
      breadcrumbs={[{ label: 'Sozlamalar' }, { label: 'Foydalanuvchilar' }]}
      actions={
        <Button variant="primary" icon={Plus} onClick={() => setModalOpen(true)}>
          Foydalanuvchi qo&apos;shish
        </Button>
      }
      tabs={tabs}
    >
      {tab === 'foydalanuvchilar' ? (
        <>
        <FilterBar
          onReset={() => {
            setSearch('');
            setRoleFilter('');
            setRiskFilter('');
          }}
          fields={[
            { kind: 'search', value: search, onChange: setSearch, placeholder: 'Ism yoki login…', ariaLabel: 'Foydalanuvchini qidirish' },
            {
              kind: 'select',
              value: roleFilter,
              onChange: setRoleFilter,
              placeholder: 'Barcha rollar',
              ariaLabel: 'Rol',
              options: [
                { value: 'super-admin', label: 'Super Admin' },
                { value: 'admin', label: 'Admin' },
                { value: 'kamera-masuli', label: "Kamera mas'uli" },
              ],
            },
            {
              kind: 'select',
              value: riskFilter,
              onChange: setRiskFilter,
              placeholder: 'Xavfsizlik: hammasi',
              ariaLabel: 'Xavfsizlik',
              options: [
                { value: '2fa_yoq', label: 'Administrator, 2FA yo‘q' },
                { value: 'eski', label: '90 kundan beri kirmagan' },
                { value: 'kirmagan', label: 'Hech kirmagan' },
              ],
            },
          ]}
        />
        <IntelPanel title="Foydalanuvchilar" right={<MicroLabel>{total} ta</MicroLabel>}>
        <DataTable
          dense
          columns={userColumns}
          rows={users}
          rowKey={(u) => u.id}
          onRowClick={(u) => setEditing(u)}
          selectedKey={editing?.id ?? null}
          loading={loading && users.length === 0}
          loadingRows={PAGE_SIZE}
          error={users.length === 0 ? error : null}
          onRetry={reload}
          emptyTitle="Foydalanuvchi yo'q"
          emptyAction={
            <Button variant="primary" icon={UserPlus} onClick={() => setModalOpen(true)}>
              Foydalanuvchi qo&apos;shish
            </Button>
          }
          ariaLabel="Foydalanuvchilar"
          maxHeight="none"
          footer={
            error && users.length > 0 ? (
              <Notice tone="danger" action={<Button size="sm" onClick={reload}>Qayta urinish</Button>}>
                {error}
              </Notice>
            ) : (
              pagerFooter({ page, totalPages, total, pageSize, onChange: setPage })
            )
          }
        />
        </IntelPanel>
        </>
      ) : (
        <div className="flex flex-col gap-3">
          {saveError && (
            <Notice
              tone="danger"
              action={
                <Button size="sm" onClick={clearSaveError}>
                  Yopish
                </Button>
              }
            >
              {saveError}
            </Notice>
          )}
          {!canEdit && (
            <Notice tone="neutral" icon={Lock}>
              Faqat Super Admin tahrirlaydi.
            </Notice>
          )}
          <IntelPanel title="Huquqlar matritsasi" right={<MicroLabel>{permissionKeys.length} ta</MicroLabel>}>
            <DataTable
              dense
              columns={permissionColumns}
              rows={permissionKeys}
              rowKey={(key) => key}
              emptyTitle="Huquqlar yuklanmadi"
              maxHeight="none"
              ariaLabel="Huquqlar matritsasi"
            />
          </IntelPanel>
        </div>
      )}

      <AddUserModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAdd={(user) => {
          toast.success(`${user.name} qo'shildi`);
          refresh();
        }}
      />
      <EditUserModal
        user={editing}
        onClose={() => setEditing(null)}
        onSave={(user) => {
          toast.success(`${user.name} — o'zgarishlar saqlandi`);
          refresh();
        }}
      />
      {scoping && (
        <UserBuildingScopeModal
          user={scoping}
          onClose={() => setScoping(null)}
          onSaved={(user) => {
            toast.success(`${user.name} — bino doirasi saqlandi`);
            refresh();
          }}
        />
      )}
      <ConfirmDialog
        open={!!resetting2fa}
        title="Ikki bosqichli kirishni bekor qilish"
        message={
          resetting2fa
            ? `"${resetting2fa.name}" keyingi safar faqat parol bilan kiradi va 2FA'ni qaytadan yoqishi kerak. Ochiq sessiyalari yopiladi.`
            : ''
        }
        confirmLabel="Bekor qilish"
        onCancel={() => setResetting2fa(null)}
        onConfirm={handleReset2fa}
      />
      <ConfirmDialog
        open={!!deleting}
        title="Foydalanuvchini o'chirish"
        message={
          deleting
            ? `"${deleting.name}" (${deleting.login}) o'chiriladi. Qaytarib bo'lmaydi.`
            : ''
        }
        confirmLabel="O'chirish"
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </Page>
  );
}

function PermissionMark({
  granted,
  lockedReason,
  label,
  busy,
  onToggle,
}: {
  granted: boolean;
  /** Qulflangan bo'lsa — NEGA qulflanganining izohi (bo'sh tooltip emas). */
  lockedReason?: string;
  label: string;
  busy?: boolean;
  onToggle?: () => void;
}) {
  if (onToggle && !lockedReason) {
    return (
      <span className="inline-flex justify-center">
        <Switch checked={granted} onChange={onToggle} label={label} disabled={busy} />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center justify-center gap-1.5">
      <span
        role="img"
        aria-label={`${label}: ${granted ? 'ruxsat bor' : "ruxsat yo'q"}${lockedReason ? `. ${lockedReason}` : ''}`}
        title={lockedReason}
        className={cn(
          'inline-flex h-5 w-5 items-center justify-center border',
          granted ? 'border-success/40 bg-success-soft text-success' : 'border-border bg-surface-2 text-subtle',
        )}
      >
        {granted ? <Check size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />}
      </span>
      {lockedReason && (
        <span className="inline-flex items-center gap-1 text-subtle" title={lockedReason}>
          <Lock size={11} aria-hidden="true" />
          <MicroLabel>Qulf</MicroLabel>
        </span>
      )}
    </span>
  );
}
