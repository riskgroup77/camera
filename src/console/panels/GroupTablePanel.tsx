import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, CalendarCheck, GraduationCap, ListChecks, Users } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
  POSITION_GROUP_LABEL,
  getGroups,
  getOrgTree,
  type GroupStat,
  type GroupStudent,
  type OrgTree,
  type PeopleStatusKey,
  type PositionGroup,
  type StatusCounts,
} from '../../lib/situationApi';
import { Button, DataTable, DatePicker, SearchInput, Select, StatusBadge, Tabs, cn, type DataTableColumn } from '../../ui';
import StatusCounters, { COUNTER_META, type CounterKey } from '../../components/situation/StatusCounters';
import StatusPeopleTable from '../../components/situation/StatusPeopleTable';
import CountPicker, { type CountOption } from '../../components/situation/CountPicker';
import PdfButton from '../../components/situation/PdfButton';
import GroupCriteriaTable from '../../components/situation/GroupCriteriaTable';
import Panel from '../Panel';
import type { GroupLive } from '../useGroupLive';
import type { GroupCriteriaState } from '../useGroupCriteria';
import type { GroupView, NazoratSelection, Who } from '../nazoratSelection';

/**
 * NAZORAT — chap jadval.
 *
 * Tepada: Talabalar | O'qituvchi va xodimlar. Filtrlar aniq nomlangan:
 *   talabalar — fakultet, kurs, guruh, holat, F.I.Sh.;
 *   xodimlar  — tuzilma (HEMIS: rahbariyat, fakultet -> kafedralar, bo'limlar,
 *               markazlar, turar joylar), lavozim toifasi (o'qituvchi /
 *               ma'muriy / texnik), lavozim, holat, F.I.Sh.
 *
 * Talabalar, guruh tanlanmagan: holat va qidiruv bo'sh bo'lsa — guruhlar
 * jadvali (sanoqlar bosiladi); holat yoki F.I.Sh. berilsa — shu filtrdagi
 * talabalarning o'zi (butun institut / fakultet / kurs bo'yicha).
 * Guruh tanlangan: guruh talabalari — holati, kelgan vaqti, hozirgi darsda
 * ko'ringanmi, yuzi bazadami. "Kriteriyalar" ko'rinishida — har talaba
 * qatorida hamma kriteriyalar va video dalillar (GroupCriteriaTable).
 */

const WHO_TABS = [
  { id: 'talaba' as const, label: 'Talabalar', icon: GraduationCap },
  { id: 'xodim' as const, label: 'O‘qituvchi va xodimlar', icon: Users },
];

const VIEW_TABS = [
  { id: 'davomat' as const, label: 'Davomat', icon: CalendarCheck },
  { id: 'kriteriyalar' as const, label: 'Kriteriyalar', icon: ListChecks },
];

const DAY_KEYS: CounterKey[] = ['hammasi', 'kelgan', 'kech_keldi', 'kelmadi', 'kutilmoqda', 'malumot_yoq', 'yuzsiz'];
const COUNT_FIELD: Record<string, keyof StatusCounts> = {
  hammasi: 'hammasi',
  kelgan: 'kelgan',
  kech_keldi: 'kechKeldi',
  kelmadi: 'kelmadi',
  kutilmoqda: 'kutilmoqda',
  malumot_yoq: 'malumotYoq',
  yuzsiz: 'yuzsiz',
};

export function studentMatches(student: GroupStudent, key: CounterKey, lessonSeen: ReadonlySet<string> | null): boolean {
  switch (key) {
    case 'hammasi':
      return true;
    case 'kelgan':
      return student.status === 'keldi' || student.status === 'kech_keldi';
    case 'kech_keldi':
    case 'kelmadi':
    case 'kutilmoqda':
      return student.status === key;
    case 'malumot_yoq':
      // Yozuvsiz o'tgan kun (server: person_status -> "malumot_yoq").
      return student.status === 'malumot_yoq';
    case 'yuzsiz':
      return student.biometricsStatus !== 'tasdiqlangan';
    case 'darsda':
      return Boolean(lessonSeen?.has(student.id));
    case 'darsda_emas':
      return Boolean(lessonSeen) && !lessonSeen!.has(student.id);
  }
}

export function lessonSeenIds(live: GroupLive): Set<string> | null {
  if (!live.current || !live.lessonRows) return null;
  return new Set(live.lessonRows.rows.filter((row) => row.firstSeenAt || row.sightings > 0).map((row) => row.studentId));
}

export function groupCounters(students: readonly GroupStudent[], seen: ReadonlySet<string> | null) {
  const keys: CounterKey[] = [...DAY_KEYS];
  if (seen) keys.push('darsda', 'darsda_emas');
  return keys.map((key) => ({ key, value: students.filter((s) => studentMatches(s, key, seen)).length }));
}

function statusOptions(keys: readonly CounterKey[]) {
  return keys.filter((k) => k !== 'hammasi').map((k) => ({ value: k, label: COUNTER_META[k].label }));
}

export default function GroupTablePanel({
  selection,
  live,
  criteria,
  canCriteria,
  date,
  setDate,
  isToday,
  pulse,
  expanded,
  onExpand,
  area,
}: {
  selection: NazoratSelection;
  live: GroupLive;
  /** Guruh kriteriyalari (hisobotlarni ko'rish huquqi bo'lsa). */
  criteria: GroupCriteriaState;
  canCriteria: boolean;
  date: string;
  setDate: (date: string) => void;
  isToday: boolean;
  pulse: number;
  expanded: boolean;
  onExpand: (id: string | null) => void;
  area?: string;
}) {
  const { who, group, status, view, setWho, setGroup, setStatus, setView } = selection;
  const students = who === 'talaba';
  const criteriaMode = students && Boolean(group) && canCriteria && view === 'kriteriyalar';
  const [groups, setGroups] = useState<GroupStat[] | null>(null);
  const [tree, setTree] = useState<OrgTree | null>(null);
  const [positionGroup, setPositionGroup] = useState<PositionGroup | ''>('');
  const [position, setPosition] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [faculty, setFaculty] = useState('');
  const [course, setCourse] = useState('');
  const [search, setSearch] = useState('');
  const [counts, setCounts] = useState<StatusCounts | null>(null);

  useEffect(() => setSearch(''), [who, group]);
  useEffect(() => {
    setPositionGroup('');
    setPosition('');
  }, [who]);

  useEffect(() => {
    const controller = new AbortController();
    const load = students
      ? getGroups({ date }, { signal: controller.signal }).then(setGroups)
      : getOrgTree(date, { signal: controller.signal }).then(setTree);
    load
      .then(() => setLoadError(null))
      .catch((err) => {
        if (!controller.signal.aborted) setLoadError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [date, pulse, students]);

  const facultyOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of groups ?? []) if (g.facultyId && g.faculty) seen.set(g.facultyId, g.faculty);
    return [...seen].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [groups]);
  const courseOptions = useMemo(() => {
    const seen = new Set<number>();
    for (const g of groups ?? []) if (g.course) seen.add(g.course);
    return [...seen].sort((a, b) => a - b).map((c) => ({ value: String(c), label: `${c}-kurs` }));
  }, [groups]);
  const filteredGroups = useMemo(
    () =>
      (groups ?? []).filter(
        (g) => g.total > 0 && (!faculty || g.facultyId === faculty) && (!course || String(g.course) === course),
      ),
    [groups, faculty, course],
  );
  const groupTotals = useMemo(() => {
    const sum = (pick: (g: GroupStat) => number) => filteredGroups.reduce((acc, g) => acc + pick(g), 0);
    return {
      hammasi: sum((g) => g.total),
      kelgan: sum((g) => g.present),
      kech_keldi: sum((g) => g.late),
      kelmadi: sum((g) => g.absent),
      kutilmoqda: sum((g) => g.notYet),
      malumot_yoq: sum((g) => g.noData),
      yuzsiz: sum((g) => g.total - g.enrolled),
    } as Record<CounterKey, number>;
  }, [filteredGroups]);
  // Ochiluvchi ro'yxatda har guruh yonida: kelgan (yashil), kelmagan (qizil), ma'lumotsiz (kulrang).
  // HEMIS guruhlari (kursi va fakulteti ma'lum) birinchi, o'zi ro'yxatdan
  // o'tganda qo'lda yozilgan noaniq nomlar ("1", "20.26 gurux") — alohida pastda.
  const groupOptions = useMemo<CountOption[]>(() => {
    const known = (g: GroupStat) => Boolean(g.course && g.facultyId);
    return [...filteredGroups]
      .sort((a, b) => Number(known(b)) - Number(known(a)) || (a.course ?? 0) - (b.course ?? 0) || a.name.localeCompare(b.name))
      .map((g) => ({
        value: g.name,
        label: g.name,
        present: g.present,
        absent: g.absent + g.notYet,
        noData: g.noData,
        section: known(g) ? `${g.course}-kurs` : 'Aniqlanmagan (qo‘lda yozilgan) guruhlar',
      }));
  }, [filteredGroups]);
  // Tuzilma daraxti: ildiz turi bo'yicha bo'limlar, kafedralar fakultet ostida.
  const unitOptions = useMemo<CountOption[]>(() => {
    let section = '';
    return (tree?.units ?? [])
      .filter((u) => u.total > 0)
      .map((u) => {
        if (u.depth === 0) section = u.kindLabel;
        return { value: u.id, label: u.name, present: u.present, absent: u.absent + u.notYet, noData: u.noData, indent: u.depth, section };
      });
  }, [tree]);
  const positionOptions = useMemo<CountOption[]>(
    () =>
      (tree?.positions ?? [])
        .filter((p) => !positionGroup || p.group === positionGroup)
        .map((p) => ({ value: p.name, label: p.name, present: p.present, absent: p.absent + p.notYet, noData: p.noData })),
    [tree, positionGroup],
  );
  const positionGroupOptions = (Object.keys(POSITION_GROUP_LABEL) as PositionGroup[]).map((key) => ({
    value: key,
    label: `${POSITION_GROUP_LABEL[key]} (${tree?.positionGroups[key] ?? 0})`,
  }));

  const seen = lessonSeenIds(live);
  const groupStudents = live.detail?.students ?? [];
  const needle = search.trim().toLowerCase();
  const shownStudents = groupStudents.filter(
    (s) => studentMatches(s, status, seen) && (!needle || s.fullName.toLowerCase().includes(needle)),
  );

  // Talabalar, guruh tanlanmagan: holat/F.I.Sh. berilsa — odamlar ro'yxati, aks holda guruhlar.
  const peopleMode = !students || (!group && (status !== 'hammasi' || needle.length > 0));

  const openGroup = (name: string, key: CounterKey = 'hammasi') => {
    setGroup(name);
    if (key !== 'hammasi') window.setTimeout(() => setStatus(key), 0);
  };

  const countCell = (row: GroupStat, key: CounterKey, value: number, tone: string) => (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        openGroup(row.name, key);
      }}
      className={cn('tabular-nums font-semibold hover:underline', tone)}
      title={`${row.name}: ${COUNTER_META[key].label.toLowerCase()} — ro‘yxat`}
    >
      {value}
    </button>
  );

  const groupColumns: DataTableColumn<GroupStat>[] = [
    { key: 'name', header: 'Guruh', sortValue: (r) => r.name, cell: (r) => <b>{r.name}</b> },
    { key: 'course', header: 'Kurs', sortValue: (r) => r.course ?? 0, cell: (r) => r.course ?? '—', align: 'center' },
    { key: 'total', header: <Hint text="Guruhdagi barcha faol talabalar">Jami</Hint>, sortValue: (r) => r.total, sortFirst: 'desc', align: 'right', cell: (r) => countCell(r, 'hammasi', r.total, 'text-fg') },
    { key: 'present', header: <Hint text="Kelganlar — kech kelganlar ham shu songa kiradi">Keldi</Hint>, sortValue: (r) => r.present, align: 'right', cell: (r) => countCell(r, 'kelgan', r.present, 'text-success') },
    { key: 'late', header: <Hint text="Kelganlardan kech kelganlari (ish boshlanishi + ruxsat etilgan daqiqalardan keyin)">Kech</Hint>, sortValue: (r) => r.late, align: 'right', cell: (r) => countCell(r, 'kech_keldi', r.late, 'text-warning') },
    { key: 'absent', header: <Hint text="Yuzi bazada bor, lekin kun davomida kamera ko‘rmagan (20:00 dan keyin belgilanadi)">Kelmadi</Hint>, sortValue: (r) => r.absent, align: 'right', cell: (r) => countCell(r, 'kelmadi', r.absent, 'text-danger') },
    { key: 'notYet', header: <Hint text="Bugun hali kamera ko‘rmagan — kun tugamagan, kelishi mumkin">Hali yo‘q</Hint>, sortValue: (r) => r.notYet, align: 'right', cell: (r) => countCell(r, 'kutilmoqda', r.notYet, 'text-muted') },
    { key: 'noFace', header: <Hint text="Yuzi bazaga kiritilmagan — kamera taniy olmaydi, davomati o‘lchanmaydi">Yuzsiz</Hint>, sortValue: (r) => r.total - r.enrolled, align: 'right', cell: (r) => countCell(r, 'yuzsiz', r.total - r.enrolled, 'text-danger') },
    { key: 'rate', header: <Hint text="Davomat foizi = keldi ÷ (keldi + kelmadi + hali yo‘q). Yuzsiz va dam olishdagilar hisobga kirmaydi">%</Hint>, sortValue: (r) => r.rate ?? -1, align: 'right', cell: (r) => (r.rate == null ? '—' : `${Math.round(r.rate)}%`) },
  ];

  const studentColumns: DataTableColumn<GroupStudent>[] = [
    { key: 'n', header: '№', width: '2.5rem', cell: (_r, i) => i + 1, mono: true },
    {
      key: 'name',
      header: 'F.I.Sh.',
      sortValue: (r) => r.fullName,
      cell: (r) => (
        <Link to={`/shaxs/${encodeURIComponent(r.id)}`} className="font-medium text-fg hover:text-primary">
          {r.fullName}
        </Link>
      ),
    },
    {
      key: 'status',
      header: 'Holat',
      sortValue: (r) => r.status,
      cell: (r) => <StatusBadge status={r.status === 'malumot_yoq' ? 'nomalum' : r.status} size="sm" />,
    },
    { key: 'checkIn', header: 'Kelgan', sortValue: (r) => r.checkIn ?? '99', cell: (r) => r.checkIn ?? '—', mono: true },
    ...(seen
      ? [
          {
            key: 'lesson',
            header: 'Hozirgi dars',
            sortValue: (r: GroupStudent) => (seen.has(r.id) ? 0 : 1),
            cell: (r: GroupStudent) =>
              seen.has(r.id) ? (
                <span className="text-[12px] font-semibold text-success">darsda</span>
              ) : (
                <span className="text-[12px] font-semibold text-danger">yo‘q</span>
              ),
          } satisfies DataTableColumn<GroupStudent>,
        ]
      : []),
    {
      key: 'face',
      header: 'Yuz',
      sortValue: (r) => (r.biometricsStatus === 'tasdiqlangan' ? 0 : 1),
      cell: (r) =>
        r.biometricsStatus === 'tasdiqlangan' ? (
          <span className="text-[12px] text-success">bazada</span>
        ) : (
          <span className="text-[12px] font-semibold text-danger">yo‘q</span>
        ),
    },
  ];

  const statusKeys: CounterKey[] = students && group && seen ? [...DAY_KEYS, 'darsda', 'darsda_emas'] : DAY_KEYS;
  const peopleQuery = students
    ? {
        date,
        type: 'talaba' as const,
        facultyId: faculty || undefined,
        course: course ? Number(course) : undefined,
        search: needle || undefined,
      }
    : {
        date,
        type: 'xodim' as const,
        orgUnitId: group || undefined,
        positionGroup: positionGroup || undefined,
        position: position || undefined,
        search: needle || undefined,
      };

  // PDF — aynan ekrandagi ko'rinish: guruh ro'yxati, bitta guruh yoki odamlar ro'yxati.
  const pdfStatus = status === 'darsda' || status === 'darsda_emas' ? 'hammasi' : status;
  const pdfTarget =
    students && group
      ? { path: '/api/situation/pdf/group', params: { name: group, date, status: pdfStatus }, filename: `guruh-${group}-${date}` }
      : peopleMode
        ? { path: '/api/situation/pdf/people', params: { ...peopleQuery, status: pdfStatus }, filename: `${who}-${pdfStatus}-${date}` }
        : {
            path: '/api/situation/pdf/groups',
            params: { date, facultyId: faculty || undefined, course: course || undefined },
            filename: `guruhlar-${date}`,
          };

  const filters = (
    <div className="flex shrink-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs<Who> tabs={WHO_TABS} value={who} onChange={setWho} variant="segmented" size="sm" ariaLabel="Kimlar" />
        <span className="ms-auto">
          <DatePicker value={date} onChange={setDate} size="sm" quick stepper ariaLabel="Sana" />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {students && group && (
          <Button size="sm" icon={ArrowLeft} onClick={() => setGroup('')}>
            Barcha guruhlar
          </Button>
        )}
        {students && group && canCriteria && (
          <Tabs<GroupView> tabs={VIEW_TABS} value={view} onChange={setView} variant="segmented" size="sm" ariaLabel="Guruh jadvali" />
        )}
        {students ? (
          <>
            {!group && (
              <>
                <Select label="Fakultet" value={faculty} onChange={setFaculty} options={facultyOptions} placeholder="hammasi" size="sm" highlightActive />
                <Select label="Kurs" value={course} onChange={setCourse} options={courseOptions} placeholder="hammasi" size="sm" highlightActive />
              </>
            )}
            <CountPicker label="Guruh" value={group} onChange={setGroup} options={groupOptions} />
          </>
        ) : (
          <>
            <CountPicker label="Tuzilma" value={group} onChange={setGroup} options={unitOptions} />
            <Select
              label="Toifa"
              value={positionGroup}
              onChange={(value) => {
                setPositionGroup(value as PositionGroup | '');
                setPosition('');
              }}
              options={positionGroupOptions}
              placeholder="hammasi"
              size="sm"
              highlightActive
            />
            <CountPicker label="Lavozim" value={position} onChange={setPosition} options={positionOptions} />
          </>
        )}
        {!criteriaMode && <Select
          label="Holat"
          value={status === 'hammasi' ? '' : status}
          onChange={(value) => setStatus((value || 'hammasi') as CounterKey)}
          options={statusOptions(statusKeys)}
          placeholder="hammasi"
          size="sm"
          highlightActive
        />}
        <SearchInput value={search} onChange={setSearch} placeholder="F.I.Sh. bo‘yicha qidirish" size="sm" className="w-52" />
        <span className="ms-auto">
          {!criteriaMode && status !== 'darsda' && status !== 'darsda_emas' && <PdfButton {...pdfTarget} />}
        </span>
      </div>
    </div>
  );

  const criteriaRows = criteria.data
    ? { ...criteria.data, people: criteria.data.people.filter((p) => !needle || p.full_name.toLowerCase().includes(needle)) }
    : null;

  let body;
  if (criteriaMode) {
    body = (
      <>
        <div className="min-h-0 flex-1">
          <GroupCriteriaTable data={criteriaRows} loading={criteria.loading} error={criteria.error} />
        </div>
        <p className="shrink-0 text-[11px] leading-snug text-muted">
          Rang: <span className="text-success">yashil</span> — yaxshi, <span className="text-warning">sariq</span> — ogohlantirish,{' '}
          <span className="text-danger">qizil</span> — muammo · kamera belgisi — 2 daqiqalik video dalil (talaba sahifasida) ·
          «—» — shu talaba uchun yozuv yo‘q. Ustunni bosing — muammolilar tepaga chiqadi.
        </p>
      </>
    );
  } else if (students && group) {
    body = (
      <>
        <StatusCounters items={groupCounters(groupStudents, seen)} active={status} onPick={setStatus} size="sm" className="shrink-0" />
        <div className="min-h-0 flex-1">
          <DataTable
            columns={studentColumns}
            rows={shownStudents}
            rowKey={(r) => r.id}
            loading={live.loading && !live.detail}
            error={live.error}
            emptyTitle={status === 'hammasi' ? 'Hech kim topilmadi' : `${COUNTER_META[status].label}: hech kim`}
            fill
            dense
          />
        </div>
      </>
    );
  } else if (peopleMode) {
    body = (
      <>
        <StatusCounters
          items={DAY_KEYS.map((key) => ({ key, value: counts ? counts[COUNT_FIELD[key]] : null }))}
          active={status}
          onPick={setStatus}
          size="sm"
          className="shrink-0"
        />
        <div className="min-h-0 flex-1">
          <StatusPeopleTable
            fill
            query={peopleQuery}
            status={(status === 'darsda' || status === 'darsda_emas' ? 'hammasi' : status) as PeopleStatusKey}
            refreshKey={pulse}
            onLoaded={(page) => setCounts(page.counts)}
          />
        </div>
      </>
    );
  } else {
    body = (
      <>
        {/* Xodimlardagi kabi umumiy sanoq — jadvaldagi guruhlar yig'indisi
            (fakultet/kurs filtri bilan); son bosilsa — shu holatdagilar ro'yxati. */}
        <StatusCounters
          items={DAY_KEYS.map((key) => ({ key, value: groups ? groupTotals[key] : null }))}
          active={status}
          onPick={setStatus}
          size="sm"
          className="shrink-0"
        />
      <div className="min-h-0 flex-1">
        <DataTable
          columns={groupColumns}
          rows={filteredGroups}
          rowKey={(r) => r.name}
          onRowClick={(r) => openGroup(r.name)}
          loading={!groups && !loadError}
          error={loadError}
          emptyTitle="Guruh topilmadi"
          fill
          // Eng katta guruhlar tepada (Jami — ko'pidan kamiga).
          defaultSort={{ key: 'total', dir: 'desc' }}
          dense
        />
      </div>
      </>
    );
  }

  const content = (
    <div className="flex h-full min-h-0 flex-col gap-2 px-3 pb-3">
      {filters}
      {body}
      {!(students && group) && (
        <p className="shrink-0 text-[11px] leading-snug text-muted">
          <b className="text-fg">Keldi</b> — kech kelganlar bilan birga · <b className="text-fg">%</b> = keldi ÷ (keldi +
          kelmadi + hali yo‘q) · <b className="text-fg">Yuzsiz</b> — kamera taniy olmaydi, foizga kirmaydi · Jami bilan farq — dam
          olishdagilar va ma’lumoti yo‘qlar. Sarlavhaga sichqonchani olib boring — izoh chiqadi.
        </p>
      )}
      {!isToday && <p className="shrink-0 text-[11px] text-muted">Arxiv: {date} holati</p>}
    </div>
  );

  const unitName = !students && group ? tree?.units.find((u) => u.id === group)?.name : null;
  const title = students ? (group ? `Guruh ${group}` : 'Talabalar') : unitName ?? 'O‘qituvchi va xodimlar';
  const badge =
    criteriaMode && criteriaRows ? `${criteriaRows.people.length} talaba`
    : students && group ? `${shownStudents.length}/${groupStudents.length}` : students && !peopleMode ? `${filteredGroups.length} guruh` : null;

  return (
    <Panel
      id="groups"
      title={title}
      live={isToday}
      expanded={expanded}
      onExpand={onExpand}
      area={area}
      clickToExpand={false}
      badge={badge ? <span className="text-[11px] tabular-nums text-muted">{badge}</span> : undefined}
      full={content}
    >
      {expanded ? null : content}
    </Panel>
  );
}


/** Ustun sarlavhasi izohi: nuqtali tagchiziq va sichqoncha ostida tushuntirish. */
function Hint({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span title={text} className="cursor-help underline decoration-dotted decoration-subtle underline-offset-2">
      {children}
    </span>
  );
}
