import { useEffect, useMemo, useState } from 'react';
import {
  POSITION_GROUP_LABEL,
  getGroups,
  getOrgTree,
  type GroupStat,
  type OrgTree,
  type PeopleStatusKey,
  type PersonType,
  type PositionGroup,
  type StatusCounts,
} from '../../lib/situationApi';
import { todayInTashkent } from '../../lib/uzDate';
import { DatePicker, IntelPanel, SearchInput, Select } from '../../ui';
import StatusCounters, { COUNTER_META, type CounterKey } from '../situation/StatusCounters';
import StatusPeopleTable from '../situation/StatusPeopleTable';
import CountPicker, { type CountOption } from '../situation/CountPicker';
import PdfButton from '../situation/PdfButton';

/**
 * Hisobot — institutning umumiy (jonli) holati. Nazoratdagi guruh ko'rinishi
 * bilan bir xil sanoqlar, lekin butun institut bo'yicha va filtrlar bilan:
 * fakultet, kurs, guruh, qidiruv, sana. Har son bosiladi — pastdagi ro'yxat
 * aynan o'sha odamlarni ko'rsatadi. Bugun bo'lsa har REFRESH_MS da yangilanadi.
 */

const REFRESH_MS = 30_000;
const KEYS: CounterKey[] = ['hammasi', 'kelgan', 'kech_keldi', 'kelmadi', 'kutilmoqda', 'yuzsiz'];
const FIELD: Record<string, keyof StatusCounts> = {
  hammasi: 'hammasi',
  kelgan: 'kelgan',
  kech_keldi: 'kechKeldi',
  kelmadi: 'kelmadi',
  kutilmoqda: 'kutilmoqda',
  yuzsiz: 'yuzsiz',
};

export default function InstituteStatusView({ type }: { type: PersonType }) {
  const [date, setDate] = useState(todayInTashkent());
  const [faculty, setFaculty] = useState('');
  const [course, setCourse] = useState('');
  const [group, setGroup] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<CounterKey>('hammasi');
  const [counts, setCounts] = useState<StatusCounts | null>(null);
  const [groups, setGroups] = useState<GroupStat[]>([]);
  const [tick, setTick] = useState(0);
  const [tree, setTree] = useState<OrgTree | null>(null);
  const [unit, setUnit] = useState('');
  const [positionGroup, setPositionGroup] = useState<PositionGroup | ''>('');
  const [position, setPosition] = useState('');
  const isToday = date === todayInTashkent();
  const students = type === 'talaba';

  useEffect(() => {
    if (!students) return;
    const controller = new AbortController();
    getGroups({ date }, { signal: controller.signal }).then(setGroups).catch(() => undefined);
    return () => controller.abort();
  }, [date, students]);

  useEffect(() => {
    if (students) return;
    const controller = new AbortController();
    getOrgTree(date, { signal: controller.signal }).then(setTree).catch(() => undefined);
    return () => controller.abort();
  }, [date, students]);

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

  useEffect(() => {
    if (!isToday) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [isToday]);

  const facultyOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of groups) if (g.facultyId && g.faculty) seen.set(g.facultyId, g.faculty);
    return [...seen].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [groups]);
  const courseOptions = useMemo(
    () =>
      [...new Set(groups.map((g) => g.course).filter((c): c is number => Boolean(c)))]
        .sort((a, b) => a - b)
        .map((c) => ({ value: String(c), label: `${c}-kurs` })),
    [groups],
  );
  const groupOptions = useMemo(
    () =>
      groups
        .filter((g) => g.total > 0 && (!faculty || g.facultyId === faculty) && (!course || String(g.course) === course))
        .map((g) => ({ value: g.name, label: g.name, present: g.present, absent: g.absent + g.notYet, noData: g.noData })),
    [groups, faculty, course],
  );

  const query = {
    date,
    type,
    facultyId: faculty || undefined,
    course: course ? Number(course) : undefined,
    group: students ? group || undefined : undefined,
    orgUnitId: !students ? unit || undefined : undefined,
    positionGroup: !students ? positionGroup || undefined : undefined,
    position: !students ? position || undefined : undefined,
    search: search.trim() || undefined,
  };

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="print-hide flex flex-wrap items-center gap-2 border border-border bg-surface px-3 py-2">
        <DatePicker value={date} onChange={setDate} size="sm" quick stepper ariaLabel="Sana" />
        {students && (
          <>
            <Select value={faculty} onChange={(v) => { setFaculty(v); setGroup(''); }} options={facultyOptions} placeholder="Barcha fakultetlar" ariaLabel="Fakultet" size="sm" highlightActive />
            <Select value={course} onChange={(v) => { setCourse(v); setGroup(''); }} options={courseOptions} placeholder="Barcha kurslar" ariaLabel="Kurs" size="sm" highlightActive />
            <CountPicker label="Guruh" value={group} onChange={setGroup} options={groupOptions} />
          </>
        )}
        {!students && (
          <>
            <CountPicker label="Tuzilma" value={unit} onChange={setUnit} options={unitOptions} />
            <Select
              label="Toifa"
              value={positionGroup}
              onChange={(v) => { setPositionGroup(v as PositionGroup | ''); setPosition(''); }}
              options={(Object.keys(POSITION_GROUP_LABEL) as PositionGroup[]).map((k) => ({
                value: k,
                label: `${POSITION_GROUP_LABEL[k]} (${tree?.positionGroups[k] ?? 0})`,
              }))}
              placeholder="hammasi"
              size="sm"
              highlightActive
            />
            <CountPicker label="Lavozim" value={position} onChange={setPosition} options={positionOptions} />
          </>
        )}
        <SearchInput value={search} onChange={setSearch} placeholder="F.I.Sh. bo‘yicha" size="sm" className="w-48" />
        <span className="ms-auto flex items-center gap-2">
          {isToday && <span className="text-[11px] font-semibold text-success">● jonli</span>}
          <PdfButton path="/api/situation/pdf/people" params={{ ...query, status }} filename={`${type}-${status}-${date}`} />
          {!students && (
            <PdfButton path="/api/situation/pdf/tuzilma" params={{ date }} filename={`tuzilma-${date}`} label="Tuzilma PDF" />
          )}
        </span>
      </div>

      <IntelPanel title={students ? 'Talabalar — umumiy holat' : 'Xodimlar — umumiy holat'}>
        <StatusCounters
          items={KEYS.map((key) => ({ key, value: counts ? counts[FIELD[key]] : null }))}
          active={status}
          onPick={setStatus}
        />
      </IntelPanel>

      <IntelPanel title={COUNTER_META[status].label} code={counts ? `${counts[FIELD[status]]} ta` : undefined}>
        <StatusPeopleTable
          query={query}
          status={status as PeopleStatusKey}
          refreshKey={tick}
          onLoaded={(page) => setCounts(page.counts)}
        />
      </IntelPanel>
    </div>
  );
}
