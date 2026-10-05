import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import {
  Button,
  CodeText,
  DataTable,
  Drawer,
  FilterBar,
  IntelPanel,
  KeyValue,
  MicroLabel,
  RAG_TEXT,
  RATE_RAG,
  Section,
  StatusLamp,
  cn,
  controlBase,
  rag,
  useToast,
  type DataTableColumn,
  type IntelStatus,
} from '../../ui';
import { RagChip } from '../hisobot/board';
import { Notice, pagerFooter } from '../settings/kit';
import { useServerPage } from '../../lib/useServerPage';
import { ApiError, api } from '../../lib/apiClient';
import {
  CHANNEL_LABELS,
  KIND_OPTIONS,
  STATUS_LABELS,
  formatLogTime,
  kindLabel,
  type NotificationLogEntry,
  type NotificationLogStatus,
} from '../../lib/notificationsApi';

const STATUS_LAMP: Record<NotificationLogStatus, IntelStatus> = {
  yuborildi: 'ok',
  xato: 'alert',
  otkazildi: 'idle',
};

/** Server yangi holat qo'shsa (masalan 'navbatda'), `STATUS_LABELS` da u
 *  bo'lmaydi: ilgari bunda Badge BO'SH chiqardi va tone `undefined` bo'lardi
 *  — jurnalda holat ustuni umuman yo'qolardi. Kanal/turda bo'lgani kabi
 *  xom qiymatga qaytamiz. */
function statusLabel(status: NotificationLogStatus): string {
  return STATUS_LABELS[status] ?? status;
}
function statusLamp(status: NotificationLogStatus): IntelStatus {
  return STATUS_LAMP[status] ?? 'idle';
}

const STATUS_OPTIONS = (Object.keys(STATUS_LABELS) as NotificationLogStatus[]).map((s) => ({ value: s, label: STATUS_LABELS[s] }));
const CHANNEL_OPTIONS = [
  { value: 'telegram', label: CHANNEL_LABELS.telegram },
  { value: 'sms', label: CHANNEL_LABELS.sms },
];
const KIND_FILTER_OPTIONS = [
  ...KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label })),
  { value: 'parent_arrival', label: kindLabel('parent_arrival') },
  { value: 'parent_absence', label: kindLabel('parent_absence') },
];

export interface LogFilters {
  search: string;
  status: string;
  channel: string;
  kind: string;
  /** Sana oralig'i (YYYY-MM-DD), ish kuni bo'yicha. */
  from: string;
  to: string;
}

const EMPTY_LOG_FILTERS: LogFilters = { search: '', status: '', channel: '', kind: '', from: '', to: '' };

/** Jurnal filtrlari — sahifaning `toolbar` joyida (Jurnal tabi). */
export function NotificationLogToolbar({
  filters,
  onChange,
  onRefresh,
}: {
  filters: LogFilters;
  onChange: (next: LogFilters) => void;
  onRefresh: () => void;
}) {
  const set = <K extends keyof LogFilters>(key: K, value: LogFilters[K]) => onChange({ ...filters, [key]: value });
  return (
    <FilterBar
      // Tozalash — bitta yozuvda: `filters` bitta obyekt, maydon-maydon
      // tozalash oxirgisidan boshqasini bekor qilardi.
      onReset={() => onChange(EMPTY_LOG_FILTERS)}
      end={
        <Button variant="ghost" icon={RefreshCw} onClick={onRefresh}>
          Yangilash
        </Button>
      }
      fields={[
        { kind: 'search', value: filters.search, onChange: (v: string) => set('search', v), placeholder: 'Qabul qiluvchi yoki matn', ariaLabel: 'Jurnaldan qidirish' },
        { kind: 'select', value: filters.status, onChange: (v: string) => set('status', v), options: STATUS_OPTIONS, placeholder: 'Barcha holatlar', ariaLabel: 'Holat' },
        { kind: 'select', value: filters.channel, onChange: (v: string) => set('channel', v), options: CHANNEL_OPTIONS, placeholder: 'Barcha kanallar', ariaLabel: 'Kanal' },
        { kind: 'select', value: filters.kind, onChange: (v: string) => set('kind', v), options: KIND_FILTER_OPTIONS, placeholder: 'Barcha turlar', ariaLabel: 'Turi' },
        {
          kind: 'custom',
          active: Boolean(filters.from || filters.to),
          onClear: () => onChange({ ...filters, from: '', to: '' }),
          render: (
            <span className="flex flex-wrap items-center gap-1.5">
              <input
                type="date"
                aria-label="Sanadan"
                value={filters.from}
                max={filters.to || undefined}
                onChange={(e) => set('from', e.target.value)}
                className={cn(controlBase, 'h-9 w-auto px-3 text-sm tabular-nums')}
              />
              <span className="text-muted" aria-hidden="true">–</span>
              <input
                type="date"
                aria-label="Sanagacha"
                value={filters.to}
                min={filters.from || undefined}
                onChange={(e) => set('to', e.target.value)}
                className={cn(controlBase, 'h-9 w-auto px-3 text-sm tabular-nums')}
              />
            </span>
          ),
        },
      ]}
    />
  );
}

const COLUMNS: DataTableColumn<NotificationLogEntry>[] = [
  {
    key: 'time',
    header: 'Vaqt',
    cell: (r) => <CodeText className="whitespace-nowrap text-[12px] text-muted">{formatLogTime(r.createdAt)}</CodeText>,
  },
  { key: 'kind', header: 'Turi', cell: (r) => <span className="whitespace-nowrap text-[13px]">{kindLabel(r.kind)}</span> },
  {
    key: 'channel',
    header: 'Kanal',
    hideOnMobile: true,
    cell: (r) => <MicroLabel>{CHANNEL_LABELS[r.channel] ?? r.channel}</MicroLabel>,
  },
  {
    key: 'recipient',
    header: 'Qabul qiluvchi',
    cell: (r) => <CodeText className="whitespace-nowrap text-[12px] text-fg">{r.recipient}</CodeText>,
  },
  {
    key: 'text',
    header: 'Xabar',
    hideOnMobile: true,
    width: '36%',
    cell: (r) => (
      <div className="min-w-0 max-w-md">
        <p className="line-clamp-2 whitespace-pre-line text-[13px] leading-[1.35] text-muted" title={r.text}>
          {r.text}
        </p>
        {r.error && <p className="mt-0.5 line-clamp-1 text-[12px] font-medium text-danger">{r.error}</p>}
      </div>
    ),
  },
  {
    key: 'status',
    header: 'Holat',
    cell: (r) => <StatusLamp status={statusLamp(r.status)} label={statusLabel(r.status)} />,
  },
];

/** Yetkazish jurnali — "nega xabar kelmadi?" savoliga javob. `refreshKey`
 *  o'zgarsa (masalan sinov xabari yuborilgach) qayta yuklanadi. Qatorni
 *  bosish — to'liq matn va xato panelda. */
export default function NotificationLogTable({
  refreshKey,
  filters = EMPTY_LOG_FILTERS,
}: {
  refreshKey: number;
  filters?: LogFilters;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const toast = useToast();
  const { items, page, setPage, totalPages, total, pageSize, loading, error, reload } = useServerPage<NotificationLogEntry>(
    '/api/notifications/log',
    {
      status: filters.status || undefined,
      channel: filters.channel || undefined,
      kind: filters.kind || undefined,
      search: filters.search || undefined,
      from: filters.from || undefined,
      to: filters.to || undefined,
    },
    20,
  );

  useEffect(() => {
    if (refreshKey) reload();
  }, [refreshKey, reload]);

  const open = items.find((r) => r.id === openId) ?? null;
  const filtered = Object.values(filters).some((v) => v.trim() !== '');

  // Yetkazilgan ulush — FAQAT shu sahifadagi qatorlar bo'yicha (server
  // umumiy yig'indini bermaydi). Shuning uchun yorliqda ham "shu
  // sahifada" deb aytiladi: hukm ko'rinayotgan narsaga tegishli.
  // "O'tkazildi" hisobga olinmaydi — u yuborishga urinish emas.
  const attempted = items.filter((r) => r.status === 'yuborildi' || r.status === 'xato');
  const deliveredRate = attempted.length ? (attempted.filter((r) => r.status === 'yuborildi').length / attempted.length) * 100 : null;
  const deliveredTone = rag(deliveredRate, RATE_RAG);

  return (
    <IntelPanel
      title="Jurnal"
      right={
        <span className="flex items-center gap-2">
          <MicroLabel>Yetkazildi</MicroLabel>
          <CodeText className={`text-[13px] font-semibold ${RAG_TEXT[deliveredTone]}`}>
            {deliveredRate === null ? '—' : `${Math.round(deliveredRate)}%`}
          </CodeText>
          <RagChip tone={deliveredTone} />
        </span>
      }
    >
      <DataTable
        columns={COLUMNS}
        rows={items}
        rowKey={(r) => r.id}
        onRowClick={(r) => setOpenId(r.id)}
        selectedKey={openId}
        rowTone={(r) => (r.status === 'xato' ? 'danger' : null)}
        loading={loading && items.length === 0}
        error={error}
        onRetry={reload}
        emptyTitle={filtered ? 'Yozuv topilmadi' : 'Xabar yuborilmagan'}
        mobileTitleKey="recipient"
        ariaLabel="Yetkazish jurnali"
        maxHeight="none"
        dense
        footer={pagerFooter({ page, totalPages, total, pageSize, onChange: setPage })}
      />

      <Drawer open={open !== null} onClose={() => setOpenId(null)} title="Xabar tafsiloti" subtitle={open ? formatLogTime(open.createdAt) : undefined}>
        {open && (
          <div className="flex flex-col gap-5">
            <KeyValue
              items={[
                { label: 'Holat', value: <StatusLamp status={statusLamp(open.status)} label={statusLabel(open.status)} /> },
                { label: 'Turi', value: kindLabel(open.kind) },
                { label: 'Kanal', value: <MicroLabel>{CHANNEL_LABELS[open.channel] ?? open.channel}</MicroLabel> },
                { label: 'Qabul qiluvchi', value: <CodeText className="text-xs">{open.recipient}</CodeText> },
                { label: 'Vaqt', value: <CodeText>{formatLogTime(open.createdAt)}</CodeText> },
                ...(open.refId && (open.kind === 'event' || open.kind === 'event_overdue')
                  ? [{
                      label: 'Hodisa',
                      value: (
                        <Link to={`/hodisalar?id=${encodeURIComponent(open.refId)}`} className="font-medium text-primary hover:underline">
                          Hodisani ochish
                        </Link>
                      ),
                    }]
                  : []),
              ]}
            />
            {open.error && (
              <Notice tone="danger" title="Xato sababi">
                {open.error}
              </Notice>
            )}
            {open.status === 'xato' && open.text.trim() && (
              <Button
                icon={RefreshCw}
                loading={resending}
                onClick={async () => {
                  setResending(true);
                  try {
                    const res = await api.post<{ ok: boolean; error: string | null }>(`/api/notifications/log/${open.id}/qayta`, {});
                    if (res.ok) toast.success('Xabar qayta yuborildi');
                    else toast.error(res.error ?? 'Yana yetmadi');
                    reload();
                  } catch (err) {
                    toast.error(err instanceof ApiError ? err.message : 'Tarmoq xatosi');
                  } finally {
                    setResending(false);
                  }
                }}
              >
                Qayta yuborish
              </Button>
            )}
            <Section title="Xabar matni">
              <p className="whitespace-pre-line break-words border border-border bg-surface-2 px-3 py-2.5 text-[13px] leading-5 text-fg">{open.text}</p>
            </Section>
          </div>
        )}
      </Drawer>
    </IntelPanel>
  );
}
