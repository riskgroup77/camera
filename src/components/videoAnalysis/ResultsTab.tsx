import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Cigarette, Clock, DoorOpen, FileSpreadsheet, GraduationCap, Shirt, UserCheck, UserX, Users } from 'lucide-react';
import {
  Badge,
  Button,
  DataTable,
  DatePicker,
  FilterBar,
  IntelPanel,
  MicroLabel,
  StatTile,
  useToast,
  type DataTableColumn,
} from '../../ui';
import { downloadBlob } from '../../lib/download';
import { usePermissions } from '../../lib/permissions';
import { pagerFooter } from '../settings/kit';
import { useAuth } from '../../lib/auth';
import { useServerPage } from '../../lib/useServerPage';
import {
  COAT_META,
  EARLY_LEAVE_META,
  RESULTS_PATH,
  RESULT_FILTERS,
  clockOf,
  lessonsSummary,
  teacherSummary,
  videoAnalysisApi,
  type CriteriaSummary,
  type DailyCriteriaRow,
  type ResultFilter,
} from '../../lib/videoAnalysisApi';

const TYPE_OPTIONS = [
  { value: 'talaba', label: 'Talabalar' },
  { value: 'xodim', label: 'Xodimlar' },
];

function attendanceBadge(row: DailyCriteriaRow) {
  if (row.attendanceStatus === 'kelmadi') return <Badge tone="danger">Kelmadi</Badge>;
  if (row.attendanceStatus === 'kech_keldi')
    return <Badge tone="warning">{row.lateMinutes ? `${row.lateMinutes} daq kech` : 'Kech keldi'}</Badge>;
  if (row.attendanceStatus === 'keldi') return <Badge tone="success">Keldi</Badge>;
  return <span className="text-muted">—</span>;
}

/** Kunlik natijalar: har odam bo'yicha barcha kriteriyalar. */
export default function ResultsTab({ lastDay }: { lastDay: string | null }) {
  const { token, role } = useAuth();
  const { can } = usePermissions();
  const toast = useToast();
  const [exporting, setExporting] = useState(false);
  const [day, setDay] = useState<string>(lastDay ?? '');
  const [type, setType] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<ResultFilter | ''>('');
  const [summary, setSummary] = useState<CriteriaSummary | null>(null);

  useEffect(() => {
    if (!day && lastDay) setDay(lastDay);
  }, [day, lastDay]);

  useEffect(() => {
    const controller = new AbortController();
    videoAnalysisApi
      .summary(day || undefined, token, { signal: controller.signal })
      .then((s) => {
        setSummary(s);
        if (!day) setDay(s.day);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSummary(null);
      });
    return () => controller.abort();
  }, [day, token]);

  const page = useServerPage<DailyCriteriaRow>(
    RESULTS_PATH,
    { day: day || undefined, type: type || undefined, q: search || undefined, filter: filter || undefined },
    25,
  );

  async function exportExcel() {
    if (!day) return;
    setExporting(true);
    try {
      downloadBlob(await videoAnalysisApi.exportXlsx(day, type || undefined, token), `kunlik-tahlil-${day}.xlsx`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Faylni yuklab bo'lmadi");
    } finally {
      setExporting(false);
    }
  }

  const toggle = (value: ResultFilter) => setFilter((current) => (current === value ? '' : value));
  const s = summary;

  const columns: DataTableColumn<DailyCriteriaRow>[] = [
    {
      key: 'person',
      header: 'Shaxs',
      cell: (r) => (
        <div className="min-w-0">
          <Link to={`/shaxs/${r.personId}`} className="block truncate text-[13px] font-medium text-fg hover:text-primary hover:underline">
            {r.fullName}
          </Link>
          <p className="truncate text-[12px] text-subtle">
            {r.type === 'talaba' ? 'Talaba' : 'Xodim'} · {r.groupOrPosition}
          </p>
        </div>
      ),
    },
    { key: 'attendance', header: 'Davomat', cell: attendanceBadge },
    {
      key: 'time',
      header: 'Keldi – ketdi',
      cell: (r) => (
        <span className="whitespace-nowrap tabular-nums text-[12px]">
          {clockOf(r.arrivedAt)} – {clockOf(r.leftAt)}
        </span>
      ),
    },
    {
      key: 'early',
      header: 'Erta ketish',
      hideOnMobile: true,
      cell: (r) =>
        r.earlyLeave && r.earlyLeave !== 'tegishli_emas' ? (
          <Badge tone={EARLY_LEAVE_META[r.earlyLeave].tone} size="sm">
            {EARLY_LEAVE_META[r.earlyLeave].label}
          </Badge>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    { key: 'lessons', header: 'Darslar', cell: (r) => <span className="whitespace-nowrap text-[12px]">{lessonsSummary(r)}</span> },
    {
      key: 'attention',
      header: 'Diqqat',
      align: 'right',
      cell: (r) =>
        r.attentionScore === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span className={r.attentionScore < 60 ? 'font-medium text-danger' : 'text-fg'}>{r.attentionScore}</span>
        ),
      sortValue: (r) => r.attentionScore,
    },
    {
      key: 'coat',
      header: 'Oq xalat',
      cell: (r) =>
        r.coatStatus && r.coatStatus !== 'talab_yoq' ? (
          <span title={`${r.coatWhiteSamples}/${r.coatSamples} kuzatuvda oq`}>
            <Badge tone={COAT_META[r.coatStatus].tone} size="sm">
              {COAT_META[r.coatStatus].label}
            </Badge>
          </span>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    {
      key: 'smoking',
      header: 'Chekish',
      align: 'right',
      hideOnMobile: true,
      cell: (r) => (r.smokingEvents ? <span className="font-medium text-danger">{r.smokingEvents}</span> : <span className="text-muted">—</span>),
    },
    {
      key: 'teacher',
      header: "O'qituvchi",
      hideOnMobile: true,
      cell: (r) => (
        <div className="text-[12px]">
          <span className={r.teacherLate || r.teacherAbsent ? 'text-warning' : 'text-fg'}>{teacherSummary(r)}</span>
          {r.teacherActivity !== null && <p className="text-subtle">faollik {r.teacherActivity}</p>}
        </div>
      ),
    },
    {
      key: 'evidence',
      header: 'Holatlar',
      align: 'right',
      cell: (r) =>
        r.evidenceCount ? (
          <Link
            to={`/shaxs/${r.personId}`}
            title="Har holat va 2 daqiqalik video dalil — odam kartasida"
            className="font-medium text-danger hover:underline"
          >
            {r.evidenceCount}
          </Link>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        <StatTile label="Keldi" value={s?.present ?? '—'} hint={s ? `${s.people} kishidan` : undefined} icon={UserCheck} tone="success" size="md" />
        <StatTile label="Kech keldi" value={s?.late ?? '—'} icon={Clock} tone="warning" onClick={() => toggle('kech')} />
        <StatTile label="Kelmadi" value={s?.absent ?? '—'} icon={UserX} tone="danger" onClick={() => toggle('kelmadi')} />
        <StatTile label="Erta ketdi" value={s?.earlyLeave ?? '—'} icon={DoorOpen} tone="warning" onClick={() => toggle('erta_ketdi')} />
        <StatTile
          label="Darsga kech / erta"
          value={s ? `${s.lessonsLate} / ${s.lessonsLeftEarly}` : '—'}
          icon={GraduationCap}
          tone="info"
          onClick={() => toggle('darsga_kech')}
        />
        <StatTile
          label="Diqqat (o'rtacha)"
          value={s?.attentionAvg ?? '—'}
          icon={Users}
          tone={s?.attentionAvg !== null && s?.attentionAvg !== undefined && s.attentionAvg < 60 ? 'danger' : 'primary'}
          onClick={() => toggle('diqqat_past')}
        />
        <StatTile
          label="Oq xalatsiz"
          value={s?.coatNo ?? '—'}
          hint={s ? `${s.coatYes} kiygan · ${s.coatUnknown} aniqlanmadi` : undefined}
          icon={Shirt}
          tone="danger"
          onClick={() => toggle('xalatsiz')}
        />
        <StatTile label="Chekish" value={s?.smoking ?? '—'} icon={Cigarette} tone="danger" onClick={() => toggle('chekish')} />
      </div>
      {s && (s.teacherOnTime || s.teacherLate || s.teacherAbsent) ? (
        <div className="flex flex-wrap gap-2">
          <MicroLabel>
            O'qituvchilar: {s.teacherOnTime} vaqtida · {s.teacherLate} kech · {s.teacherAbsent} kelmadi
            {s.teacherActivityAvg !== null ? ` · faollik ${s.teacherActivityAvg}` : ''}
          </MicroLabel>
          <button type="button" className="text-[12px] text-primary hover:underline" onClick={() => toggle('oqituvchi_kech')}>
            ko'rsatish
          </button>
        </div>
      ) : null}

      <FilterBar
        onReset={() => {
          setType('');
          setSearch('');
          setFilter('');
        }}
        fields={[
          { kind: 'search', value: search, onChange: setSearch, placeholder: 'Ism yoki guruh…', ariaLabel: 'Qidirish' },
          {
            kind: 'custom',
            active: false,
            render: day ? <DatePicker value={day} onChange={setDay} quick stepper ariaLabel="Kun" /> : null,
          },
          { kind: 'select', value: type, onChange: setType, options: TYPE_OPTIONS, placeholder: 'Hammasi', ariaLabel: 'Turi' },
          {
            kind: 'select',
            value: filter,
            onChange: (v: string) => setFilter(v as ResultFilter | ''),
            options: RESULT_FILTERS.map((f) => ({ value: f.value, label: f.label })),
            placeholder: 'Barcha kriteriyalar',
            ariaLabel: 'Kriteriya',
          },
        ]}
      />

      <IntelPanel
        title={`Natijalar — ${day || '…'}`}
        right={
          <div className="flex items-center gap-2">
            <MicroLabel>{page.loading && page.items.length === 0 ? '—' : `${page.total} kishi`}</MicroLabel>
            {can('exportData', role) && (
              <Button size="sm" variant="ghost" icon={FileSpreadsheet} loading={exporting} disabled={!day} onClick={() => void exportExcel()}>
                Excel
              </Button>
            )}
          </div>
        }
      >
        <DataTable
          columns={columns}
          rows={page.items}
          rowKey={(r) => r.personId}
          rowTone={(r) => (r.attendanceStatus === 'kelmadi' || r.coatStatus === 'kiymagan' || r.smokingEvents ? 'danger' : null)}
          loading={page.loading && page.items.length === 0}
          error={page.error}
          onRetry={page.reload}
          emptyTitle="Natija yo'q"
          emptyDescription="Bu kun hali tahlil qilinmagan yoki filtrga mos odam yo'q."
          mobileTitleKey="person"
          ariaLabel="Kunlik natijalar"
          maxHeight="none"
          dense
          footer={pagerFooter({
            page: page.page,
            totalPages: page.totalPages,
            total: page.total,
            pageSize: page.pageSize,
            onChange: page.setPage,
          })}
        />
      </IntelPanel>
    </div>
  );
}
