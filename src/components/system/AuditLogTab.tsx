import { useEffect, useState } from 'react';
import { calendarDateInTashkent } from '../../lib/uzDate';
import { AlertCircle, AlertTriangle, CheckCircle2, Download } from 'lucide-react';
import { api, buildQuery, type Page } from '../../lib/apiClient';
import { exportRowsAsCsv } from '../../lib/csvExport';
import { useServerPage } from '../../lib/useServerPage';
import type { AuditLogEntry } from '../../types';
import {
  Button,
  CodeText,
  DataTable,
  FilterBar,
  IntelPanel,
  MicroLabel,
  StatusLamp,
  cn,
  filterActiveCount,
  focusRing,
  formatNumber,
  useToast,
  type DataTableColumn,
  type FilterFieldEntry,
  type IntelStatus,
  type Tone,
} from '../../ui';
import { Pager } from './Pager';
import { formatServerTime } from './parts';
import type { AuditStatus } from './systemTypes';

const STATUS: Record<AuditStatus, { label: string; tone: Tone }> = {
  muvaffaqiyatli: { label: 'Muvaffaqiyatli', tone: 'success' },
  xatolik: { label: 'Xatolik', tone: 'danger' },
  ogohlantirish: { label: 'Ogohlantirish', tone: 'warning' },
};

const MODULES = [
  'Autentifikatsiya',
  'Foydalanuvchilar',
  'Kameralar',
  'AI Modullari',
  'Talabalar',
  'Tashkilot',
  "Ta'lim",
  'Davomat',
  'Hisobotlar',
  'Bildirishnomalar',
  'Integratsiyalar',
  'Maxfiylik',
  'Tizim',
  'Xavfsizlik',
];

const PAGE_SIZE = 20;
const MAX_EXPORT_ROWS = 20_000;

const TILES: Array<{ id: AuditStatus; label: string; icon: typeof CheckCircle2; lamp: IntelStatus }> = [
  { id: 'muvaffaqiyatli', label: 'Muvaffaqiyatli', icon: CheckCircle2, lamp: 'ok' },
  { id: 'xatolik', label: 'Xatoliklar', icon: AlertCircle, lamp: 'alert' },
  { id: 'ogohlantirish', label: 'Ogohlantirishlar', icon: AlertTriangle, lamp: 'warn' },
];

/** Tanlangan hisoblagichning chap chekkasi — rang emas, ustun bilan. */
const TILE_MARK: Record<AuditStatus, string> = {
  muvaffaqiyatli: 'border-s-success',
  xatolik: 'border-s-danger',
  ogohlantirish: 'border-s-warning',
};

const LAMP: Record<AuditStatus, IntelStatus> = {
  muvaffaqiyatli: 'ok',
  xatolik: 'alert',
  ogohlantirish: 'warn',
};

const COLUMNS: DataTableColumn<AuditLogEntry>[] = [
  { key: 'timestamp', header: 'Vaqt', width: '11rem', cell: (row) => <CodeText className="whitespace-nowrap text-xs text-muted">{formatServerTime(row.timestamp, true) ?? '—'}</CodeText> },
  { key: 'user', header: 'Foydalanuvchi', cell: (row) => <span className="font-medium text-fg">{row.user}</span> },
  { key: 'action', header: 'Amal', cell: (row) => <span className="text-fg">{row.action}</span> },
  { key: 'module', header: 'Modul' },
  {
    key: 'status',
    header: 'Holat',
    cell: (row) => <StatusLamp status={LAMP[row.status] ?? 'idle'} label={STATUS[row.status]?.label ?? row.status} />,
  },
  { key: 'ip', header: 'IP manzil', hideOnMobile: true, cell: (row) => <CodeText className="text-xs text-muted">{row.ip}</CodeText> },
];

/** "Jurnal" tabi: kim, qachon, nima qildi (audit). */
export function AuditLogTab({ canExport }: { canExport: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState<AuditStatus | ''>('');
  const [module, setModule] = useState('');
  const [counts, setCounts] = useState<Record<AuditStatus, number> | null>(null);
  // Hisoblagichlar so'rovi xato bersa `counts` null qolib, plitkalar cheksiz
  // "yuklanmoqda" skeletonida turardi. Endi urinish tugagani alohida belgilanadi.
  const [countsDone, setCountsDone] = useState(false);
  const [exporting, setExporting] = useState(false);

  const { items, page, setPage, totalPages, total, loading, error, reload } = useServerPage<AuditLogEntry>(
    '/api/audit-log',
    { status: status || undefined, module: module || undefined },
    PAGE_SIZE,
  );

  useEffect(() => {
    const controller = new AbortController();
    setCountsDone(false);
    void (async () => {
      try {
        const [ok, err, warn] = await Promise.all(
          (Object.keys(STATUS) as AuditStatus[]).map((s) =>
            api.get<Page<AuditLogEntry>>(`/api/audit-log${buildQuery({ status: s, module: module || undefined, pageSize: 1 })}`, undefined, { signal: controller.signal }),
          ),
        );
        if (!controller.signal.aborted) setCounts({ muvaffaqiyatli: ok.total, xatolik: err.total, ogohlantirish: warn.total });
      } catch {
        /* hisoblagichlar ixtiyoriy — jadval o'z xatosini ko'rsatadi */
      } finally {
        // Urinish tugadi: muvaffaqiyatsiz bo'lsa ham plitkalar skeletondan chiqadi.
        if (!controller.signal.aborted) setCountsDone(true);
      }
    })();
    return () => controller.abort();
  }, [module]);

  async function handleExport() {
    setExporting(true);
    try {
      const all: AuditLogEntry[] = [];
      let current = 1;
      let pages = 1;
      do {
        const res = await api.get<Page<AuditLogEntry>>(
          `/api/audit-log${buildQuery({ status: status || undefined, module: module || undefined, page: current, pageSize: 500 })}`,
        );
        all.push(...res.items);
        pages = res.totalPages;
        current += 1;
      } while (current <= pages && all.length < MAX_EXPORT_ROWS);
      // Jurnal yuz minglab yozuvdan iborat bo'lishi mumkin — chegarasiz yig'ish
      // brauzerni muzlatardi. Kesilgani foydalanuvchidan yashirilmaydi.
      const truncated = all.length > MAX_EXPORT_ROWS || (current <= pages && all.length >= MAX_EXPORT_ROWS);
      if (all.length > MAX_EXPORT_ROWS) all.length = MAX_EXPORT_ROWS;
      // Bo'sh fayl yuklab berish — "ishladi" degan taassurot qoldirib,
      // amalda hech nima bermaydi. Sababi aytiladi.
      if (all.length === 0) {
        toast.info(
          activeCount > 0
            ? "Tanlangan filtrlarga mos yozuv yo'q — eksport qilinmadi"
            : "Jurnalda hali yozuv yo'q — eksport qilinmadi",
        );
        return;
      }
      exportRowsAsCsv(
        ['Vaqt', 'Foydalanuvchi', 'Amal', 'Modul', 'Holat', 'IP manzil'],
        all.map((l) => [l.timestamp, l.user, l.action, l.module, STATUS[l.status]?.label ?? l.status, l.ip]),
        `tizim-jurnali-${calendarDateInTashkent()}.csv`,
      );
      if (truncated) toast.info(`Eksport ${formatNumber(MAX_EXPORT_ROWS)} ta yozuv bilan cheklandi — davrni filtrlab qayta yuklang`);
    } catch {
      toast.error("Jurnalni eksport qilib bo'lmadi");
    } finally {
      setExporting(false);
    }
  }

  const toggleStatus = (s: AuditStatus) => setStatus((cur) => (cur === s ? '' : s));
  const filterFields: FilterFieldEntry[] = [
    {
      kind: 'select',
      value: status,
      onChange: (v) => setStatus(v as AuditStatus | ''),
      placeholder: 'Barcha holatlar',
      ariaLabel: 'Holat',
      options: (Object.keys(STATUS) as AuditStatus[]).map((s) => ({ value: s, label: STATUS[s].label })),
    },
    {
      kind: 'select',
      value: module,
      onChange: setModule,
      placeholder: 'Barcha modullar',
      ariaLabel: 'Modul',
      options: MODULES.map((m) => ({ value: m, label: m })),
    },
  ];
  const activeCount = filterActiveCount(filterFields);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <IntelPanel title="Holatlar" brackets={false} bodyClassName="grid grid-cols-1 gap-px bg-border sm:grid-cols-3">
        {TILES.map((tile) => {
          const on = status === tile.id;
          const pending = !counts && !countsDone;
          return (
            <button
              key={tile.id}
              type="button"
              aria-pressed={on}
              onClick={() => toggleStatus(tile.id)}
              className={cn(
                'min-w-0 border-s-2 bg-surface px-2.5 py-2 text-start hover:bg-surface-2',
                on ? TILE_MARK[tile.id] : 'border-s-transparent',
                focusRing,
              )}
            >
              {/* Tanlanganlik faqat ramka rangi bilan ko'rsatilardi — rangni
                  ajratolmaydigan foydalanuvchi filtr yoqiqligini bilmasdi. */}
              <span className="flex items-center gap-2">
                <StatusLamp status={tile.lamp} label={on ? `${tile.label} · filtr yoqilgan` : tile.label} />
              </span>
              <span className="mt-0.5 flex items-baseline gap-1.5">
                <CodeText className="text-[17px] font-semibold leading-tight text-fg">
                  {pending ? '…' : counts ? formatNumber(counts[tile.id]) : '—'}
                </CodeText>
                <MicroLabel className="!text-subtle">yozuv</MicroLabel>
              </span>
            </button>
          );
        })}
      </IntelPanel>

      <FilterBar
        fields={filterFields}
        end={
          <Button
            variant="secondary"
            icon={Download}
            loading={exporting}
            disabled={!canExport}
            title={canExport ? undefined : "Eksport huquqi yo'q"}
            onClick={handleExport}
          >
            CSV
          </Button>
        }
      />

      <IntelPanel title="Jurnal" right={<MicroLabel>{formatNumber(total)} ta</MicroLabel>} bodyClassName="min-w-0">
      <DataTable
        ariaLabel="Tizim jurnali"
        columns={COLUMNS}
        rows={items}
        rowKey={(row) => row.id}
        rowTone={(row) => (row.status === 'xatolik' ? 'danger' : row.status === 'ogohlantirish' ? 'warning' : null)}
        loading={loading && items.length === 0}
        error={error}
        onRetry={reload}
        manualSort
        dense
        emptyTitle="Yozuv topilmadi"
        footer={<Pager page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE} onChange={setPage} />}
      />
      </IntelPanel>

    </div>
  );
}
