import { useCallback, useEffect, useMemo, useState } from 'react';
import { BellRing, History, Pencil, Plus, Radio, Trash2 } from 'lucide-react';
import {
  Button,
  CodeText,
  ConfirmDialog,
  DataTable,
  IconButton,
  IntelPanel,
  MicroLabel,
  Page,
  StatusLamp,
  useToast,
  useUrlTab,
  type DataTableColumn,
  type TabItem,
} from '../../ui';
import { Notice, Switch } from '../../components/settings/kit';
import NotificationRuleModal from '../../components/notifications/NotificationRuleModal';
import NotificationStatusCard from '../../components/notifications/NotificationStatusCard';
import { ParentCoverageCard } from '../../components/notifications/ParentCoverageCard';
import NotificationLogTable, { NotificationLogToolbar, type LogFilters } from '../../components/notifications/NotificationLogTable';
import MyTelegramCard from '../../components/notifications/MyTelegramCard';
import TestMessageModal from '../../components/notifications/TestMessageModal';
import { ApiError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { useAiModules } from '../../lib/useAiModules';
import { useApiResource } from '../../lib/useApiResource';
import { useBuildings } from '../../lib/useBuildings';
import { describeRuleFilters, kindLabel, notificationsApi, type NotificationRule, type NotificationStatus } from '../../lib/notificationsApi';

type Tab = 'qoidalar' | 'kanallar' | 'jurnal';

export default function NotificationsPage() {
  const { token } = useAuth();
  const toast = useToast();
  const { modules } = useAiModules();
  const { buildings } = useBuildings();
  const { data: status, loading: statusLoading, error: statusError, reload: reloadStatus } = useApiResource<NotificationStatus>('/api/notifications/status');

  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [editing, setEditing] = useState<NotificationRule | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [deleting, setDeleting] = useState<NotificationRule | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [logRefresh, setLogRefresh] = useState(0);
  const [logFilters, setLogFilters] = useState<LogFilters>({ search: '', status: '', channel: '', kind: '', from: '', to: '' });

  const tabs = useMemo<readonly TabItem<Tab>[]>(
    () => [
      { id: 'qoidalar', label: 'Qoidalar', icon: BellRing, count: rulesLoading ? null : rules.length },
      { id: 'kanallar', label: 'Kanallar', icon: Radio },
      { id: 'jurnal', label: 'Yetkazish jurnali', icon: History },
    ],
    [rulesLoading, rules.length],
  );
  const [tab] = useUrlTab(tabs);

  const loadRules = useCallback(async () => {
    if (!token) return;
    setRulesLoading(true);
    try {
      setRules(await notificationsApi.rules(token));
      setRulesError(null);
    } catch (err) {
      setRulesError(err instanceof ApiError ? err.message : "Qoidalarni yuklab bo'lmadi");
    } finally {
      setRulesLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  const moduleName = useMemo(() => {
    const byCode = new Map(modules.map((m) => [m.code, m.name]));
    return (code: number) => byCode.get(code) ?? `#${code}`;
  }, [modules]);
  const buildingName = useMemo(() => {
    const byId = new Map(buildings.map((b) => [b.id, b.name]));
    return (id: string) => byId.get(id) ?? "o'chirilgan bino";
  }, [buildings]);

  function openCreate() {
    setEditing(null);
    setModalOpen(true);
  }

  function openEdit(rule: NotificationRule) {
    setEditing(rule);
    setModalOpen(true);
  }

  function handleSaved(saved: NotificationRule) {
    setRules((list) => {
      const exists = list.some((r) => r.id === saved.id);
      return exists ? list.map((r) => (r.id === saved.id ? saved : r)) : [...list, saved];
    });
    toast.success(editing ? 'Qoida saqlandi' : "Qoida qo'shildi");
  }

  async function toggleEnabled(rule: NotificationRule) {
    setTogglingId(rule.id);
    try {
      // Server tasdiqlagandan KEYIN ro'yxat yangilanadi — tugma "yoqildi"
      // deb ko'rsatib, aslida hech narsa o'zgarmagan holat bo'lmasin.
      const saved = await notificationsApi.updateRule(rule.id, { enabled: !rule.enabled }, token);
      setRules((list) => list.map((r) => (r.id === saved.id ? saved : r)));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Qoidani o'zgartirib bo'lmadi");
    } finally {
      setTogglingId(null);
    }
  }

  async function handleDelete() {
    if (!deleting) return;
    await notificationsApi.deleteRule(deleting.id, token);
    setRules((list) => list.filter((r) => r.id !== deleting.id));
    setDeleting(null);
    toast.success("Qoida o'chirildi");
  }

  const noChannel = status && !status.telegramConfigured && !status.smsConfigured;

  const columns: DataTableColumn<NotificationRule>[] = [
    {
      key: 'name',
      header: 'Qoida',
      sortValue: (r) => r.name,
      cell: (rule) => (
        <div className="min-w-0">
          <p className={`truncate text-[13px] font-medium ${rule.enabled ? 'text-fg' : 'text-muted'}`}>{rule.name}</p>
          <p className="truncate" title={rule.recipients.join(', ')}>
            <CodeText className="text-[11px] text-subtle">
              {rule.channel === 'telegram' ? 'TG' : 'SMS'} · {rule.recipients.join(', ')}
            </CodeText>
          </p>
        </div>
      ),
    },
    {
      key: 'kinds',
      header: 'Signallar',
      mobileLabel: 'Signallar',
      cell: (rule) => (
        <ul className="flex flex-wrap justify-end gap-x-2 gap-y-0.5 md:justify-start">
          {rule.kinds.map((kind) => (
            <li key={kind} className="intel-micro !text-fg">
              {kindLabel(kind)}
            </li>
          ))}
        </ul>
      ),
    },
    {
      key: 'filters',
      header: 'Cheklovlar',
      hideOnMobile: true,
      cell: (rule) => {
        const filters = describeRuleFilters(rule, moduleName, buildingName);
        return filters.length ? (
          <ul className="max-w-xs space-y-0.5 text-[12px] leading-4 text-muted">
            {filters.map((f) => (
              <li key={f} className="line-clamp-2">
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <MicroLabel>Hammasi</MicroLabel>
        );
      },
    },
    {
      key: 'enabled',
      header: 'Holat',
      sortValue: (r) => (r.enabled ? 1 : 0),
      cell: (rule) => (
        <div onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-2">
          <Switch
            checked={rule.enabled}
            disabled={togglingId === rule.id}
            onChange={() => void toggleEnabled(rule)}
            label={`${rule.name}: ${rule.enabled ? "o'chirish" : 'yoqish'}`}
          />
          <StatusLamp
            status={togglingId === rule.id ? 'idle' : rule.enabled ? 'ok' : 'idle'}
            label={togglingId === rule.id ? 'Saqlanmoqda' : rule.enabled ? 'Yoqilgan' : "O'chiq"}
          />
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      mobileLabel: 'Amallar',
      cell: (rule) => (
        <div onClick={(e) => e.stopPropagation()} className="flex justify-end gap-1">
          <IconButton icon={Pencil} label={`${rule.name} ni tahrirlash`} size="sm" onClick={() => openEdit(rule)} />
          <IconButton icon={Trash2} label={`${rule.name} ni o'chirish`} size="sm" variant="danger" onClick={() => setDeleting(rule)} />
        </div>
      ),
    },
  ];

  return (
    <Page
      title="Bildirishnomalar"
      breadcrumbs={[{ label: 'Sozlamalar' }, { label: 'Bildirishnomalar' }]}
      actions={
        <>
          <Button variant="primary" icon={Plus} onClick={openCreate}>
            Yangi qoida
          </Button>
        </>
      }
      tabs={tabs}
      toolbar={
        tab === 'jurnal' ? (
          <NotificationLogToolbar filters={logFilters} onChange={setLogFilters} onRefresh={() => setLogRefresh((n) => n + 1)} />
        ) : undefined
      }
    >
      <div className="flex min-w-0 flex-col gap-3">
        {noChannel && tab !== 'jurnal' && (
          <Notice tone="warning" title="Kanal sozlanmagan">
            Qoidalar saqlanadi, lekin xabar yuborilmaydi.
          </Notice>
        )}

        {tab === 'qoidalar' && (
          <IntelPanel title="Qoidalar" right={<MicroLabel>{rulesLoading && rules.length === 0 ? '—' : `${rules.length} ta`}</MicroLabel>}>
            <DataTable
              columns={columns}
              rows={rules}
              rowKey={(r) => r.id}
              onRowClick={openEdit}
              rowTone={(r) => (r.enabled ? null : 'neutral')}
              loading={rulesLoading && rules.length === 0}
              loadingRows={3}
              error={rulesError}
              onRetry={() => void loadRules()}
              dense
              emptyTitle="Qoida yo'q"
              emptyAction={
                <Button variant="primary" icon={Plus} onClick={openCreate}>
                  Yangi qoida
                </Button>
              }
              ariaLabel="Bildirishnoma qoidalari"
              maxHeight="none"
            />
          </IntelPanel>
        )}

        {tab === 'kanallar' && (
          <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
            <NotificationStatusCard status={status} loading={statusLoading} error={statusError} onRetry={reloadStatus} onTest={() => setTestOpen(true)} />
            <MyTelegramCard />
            <ParentCoverageCard />
          </div>
        )}

        {tab === 'jurnal' && <NotificationLogTable refreshKey={logRefresh} filters={logFilters} />}
      </div>

      <NotificationRuleModal open={modalOpen} rule={editing} status={status} onClose={() => setModalOpen(false)} onSaved={handleSaved} />
      <TestMessageModal open={testOpen} status={status} onClose={() => setTestOpen(false)} onSent={() => setLogRefresh((n) => n + 1)} />
      <ConfirmDialog
        open={!!deleting}
        title="Qoidani o'chirish"
        message={`"${deleting?.name ?? ''}" o'chiriladi — xabarlar yuborilmaydi.`}
        confirmLabel="O'chirish"
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </Page>
  );
}
