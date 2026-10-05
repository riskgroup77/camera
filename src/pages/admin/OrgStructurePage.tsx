import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, Building2, Landmark, Network, Pencil, Plus, Trash2, Users2 } from 'lucide-react';
import {
  Button,
  CodeText,
  ConfirmDialog,
  DataTable,
  ErrorState,
  FilterBar,
  IntelPanel,
  MicroLabel,
  StatusLamp,
  filterActiveCount,
  formatNumber,
  IconButton,
  Page,
  useToast,
  useUrlTab,
  type DataTableColumn,
  type FilterFieldEntry,
  type TabItem,
} from '../../ui';
import AddBuildingModal from '../../components/admin/AddBuildingModal';
import { ApiError, api, isAbortError } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { getOrgTree, situationPaths, type OrgNode } from '../../lib/situationApi';
import PdfButton from '../../components/situation/PdfButton';
import type { Building, Department, Faculty, StudentGroup } from '../../types';

type TabId = 'hemis' | 'binolar' | 'fakultetlar' | 'guruhlar' | 'kafedralar';

type DeleteTarget =
  | { kind: 'building'; item: Building }
  | { kind: 'faculty'; item: Faculty }
  | { kind: 'group'; item: StudentGroup }
  | { kind: 'department'; item: Department };

const DELETE_META: Record<DeleteTarget['kind'], { noun: string; path: string }> = {
  building: { noun: 'korpus', path: '/api/buildings' },
  faculty: { noun: 'fakultet', path: '/api/faculties' },
  group: { noun: 'guruh', path: '/api/student-groups' },
  department: { noun: 'kafedra', path: '/api/departments' },
};

/**
 * O'chirish tasdig'ida AYNAN nima yo'qolishi va nima saqlanib qolishi
 * yoziladi. Ilgari hamma tur uchun bitta matn turardi ("butunlay
 * o'chiriladi") — holbuki backendda oqibatlar juda har xil:
 * fakultet o'chirilsa uning GURUHLARI ham CASCADE bilan ketadi
 * (app/models/org.py: student_groups.faculty_id ondelete="CASCADE"),
 * bino o'chirilsa qavat rasmlari (floor_plans) ketadi, kameralar esa
 * qolib binosiz bo'ladi. Admin buni tasdiqlashdan oldin bilishi shart.
 */
export function deleteConsequences(target: DeleteTarget, groupsInFaculty: number): { lost: string[]; kept: string[] } {
  const { kind, item } = target;
  if (kind === 'building') {
    const building = item as Building;
    return {
      lost: ['Qavat sxemalari'],
      kept: [
        building.cameraCount > 0 ? `${formatNumber(building.cameraCount)} ta kamera — binosiz qoladi` : 'Kameralar',
        'Kafedralar — binosiz qoladi',
        'Turniketlar — binosiz qoladi',
      ],
    };
  }
  if (kind === 'faculty') {
    const faculty = item as Faculty;
    return {
      lost: [groupsInFaculty > 0 ? `${formatNumber(groupsInFaculty)} ta guruh` : 'Guruhlar (hozircha yo‘q)'],
      kept: [
        faculty.studentCount > 0 ? `${formatNumber(faculty.studentCount)} ta talaba — fakultetsiz qoladi` : 'Talabalar reestri',
        'Davomat tarixi',
      ],
    };
  }
  if (kind === 'group') {
    const group = item as StudentGroup;
    return {
      lost: ['Guruh kesimidagi davomat sahifasi'],
      kept: [
        group.studentCount > 0 ? `${formatNumber(group.studentCount)} ta talaba` : 'Talabalar reestri',
        'Davomat tarixi',
      ],
    };
  }
  const department = item as Department;
  return {
    lost: ["Kafedra bo'yicha filtr"],
    kept: [
      department.cameraCount > 0 ? `${formatNumber(department.cameraCount)} ta kamera — kafedrasiz qoladi` : 'Kameralar',
      'Xodimlar reestri',
    ],
  };
}

const ADD_LABEL: Record<TabId, string> = {
  hemis: '',
  binolar: "Korpus qo'shish",
  fakultetlar: '',
  guruhlar: '',
  kafedralar: '',
};

function matches(text: string | null | undefined, query: string): boolean {
  return (text ?? '').toLocaleLowerCase('uz').includes(query);
}

/** Qator ichidagi tugmalar — qator bosilishi (havola) bilan to'qnashmasin. */
function RowActions({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex items-center justify-end gap-1"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {children}
    </div>
  );
}

function NameCell({ name }: { name: string }) {
  return <span className="block min-w-0 truncate text-[13px] font-medium text-fg">{name}</span>;
}

/** Sanoq ustuni — monoshrift, tabulyatsiyali: ustma-ust raqamlar tekis turadi. */
function Count({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-subtle">kiritilmagan</span>;
  return <CodeText className="text-[12px] text-fg">{formatNumber(value)}</CodeText>;
}

export default function OrgStructurePage() {
  const { token, role } = useAuth();
  const { can } = usePermissions();
  const navigate = useNavigate();
  const toast = useToast();
  // O'qish hammaga ochiq (kamera mas'uli binolar ro'yxatini ko'radi),
  // o'zgartirish tugmalari faqat huquqi borlarga. Server ham tekshiradi.
  const canEdit = can('manageOrgStructure', role);
  // Fakultet/guruh/kafedra sahifalari davomat huquqini talab qiladi.
  const canOpenAttendance = can('manageAttendance', role);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [faculties, setFaculties] = useState<Faculty[]>([]);
  const [groups, setGroups] = useState<StudentGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const [search, setSearch] = useState('');
  const [facultyFilter, setFacultyFilter] = useState('');
  const [courseFilter, setCourseFilter] = useState('');

  const [addOpen, setAddOpen] = useState<TabId | null>(null);
  // HEMIS tuzilmasi (rektorat → fakultet → kafedra, bo'limlar) — davomat
  // sanoqlari bilan. Faqat davomat/hisobot huquqi borlarga.
  const canSeeTree = canOpenAttendance || can('viewReports', role);
  const [tree, setTree] = useState<OrgNode[] | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  useEffect(() => {
    if (!canSeeTree) return;
    const controller = new AbortController();
    getOrgTree(undefined, { signal: controller.signal })
      .then((res) => {
        setTree(res.units);
        setTreeError(null);
      })
      .catch((err: unknown) => {
        if (!isAbortError(err)) setTreeError(err instanceof ApiError ? err.message : "Tuzilmani yuklab bo'lmadi");
      });
    return () => controller.abort();
  }, [canSeeTree, nonce]);
  const [editingBuilding, setEditingBuilding] = useState<Building | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  useEffect(() => {
    if (!token) {
      // Token yo'q bo'lsa so'rov yuborilmaydi — `loading` true qolsa sahifa
      // abadiy skeleton ko'rsatib turardi. "Yuklanmoqda" emas, "ma'lumot
      // yo'q" — tugallangan holat.
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const opts = { signal: controller.signal };
    setLoading(true);
    Promise.all([
      api.get<Building[]>('/api/buildings', token, opts),
      api.get<Department[]>('/api/departments', token, opts),
      api.get<Faculty[]>('/api/faculties', token, opts),
      api.get<StudentGroup[]>('/api/student-groups', token, opts),
    ])
      .then(([b, d, f, g]) => {
        setBuildings(b);
        setDepartments(d);
        setFaculties(f);
        setGroups(g);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Tuzilmani yuklab bo'lmadi");
        setLoading(false);
      });
    return () => controller.abort();
  }, [token, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const tabs = useMemo<TabItem<TabId>[]>(
    () => [
      ...(canSeeTree ? [{ id: 'hemis' as const, label: 'HEMIS tuzilmasi', icon: Network, count: tree ? tree.length : null }] : []),
      { id: 'binolar', label: 'Binolar', icon: Building2, count: loading ? null : buildings.length },
      { id: 'fakultetlar', label: 'Fakultetlar', icon: BookOpen, count: loading ? null : faculties.length },
      { id: 'guruhlar', label: 'Guruhlar', icon: Users2, count: loading ? null : groups.length },
      { id: 'kafedralar', label: 'Kafedralar', icon: Landmark, count: loading ? null : departments.length },
    ],
    [loading, buildings.length, faculties.length, groups.length, departments.length, canSeeTree, tree],
  );
  const [tab] = useUrlTab(tabs);

  // Bo'lim almashganda filtrlar tozalanadi. Ilgari "Binolar"da yozilgan
  // qidiruv "Fakultetlar"ga o'tganda ham qo'llanib turardi: jadval bo'sh
  // chiqar, sababi esa boshqa tabdagi matn edi.
  const previousTab = useRef(tab);
  useEffect(() => {
    if (previousTab.current === tab) return;
    previousTab.current = tab;
    setSearch('');
    setFacultyFilter('');
    setCourseFilter('');
  }, [tab]);

  const query = search.trim().toLocaleLowerCase('uz');

  const shownBuildings = useMemo(() => buildings.filter((b) => matches(b.name, query)), [buildings, query]);
  const shownFaculties = useMemo(() => faculties.filter((f) => matches(f.name, query)), [faculties, query]);
  const shownDepartments = useMemo(
    () => departments.filter((d) => matches(d.name, query) || matches(d.buildingName, query)),
    [departments, query],
  );
  const shownGroups = useMemo(
    () =>
      groups.filter(
        (g) =>
          matches(g.name, query) &&
          (!facultyFilter || g.faculty === facultyFilter) &&
          (!courseFilter || String(g.course) === courseFilter),
      ),
    [groups, query, facultyFilter, courseFilter],
  );

  const courseOptions = useMemo(
    () =>
      Array.from(new Set(groups.map((g) => g.course)))
        .sort((a, b) => a - b)
        .map((c) => ({ value: String(c), label: `${c}-kurs` })),
    [groups],
  );

  async function confirmDelete() {
    if (!deleteTarget) return;
    const { kind, item } = deleteTarget;
    try {
      await api.del(`${DELETE_META[kind].path}/${item.id}`, token);
    } catch (err) {
      // ConfirmDialog xatoni o'z ichida ko'rsatadi va yopilmaydi.
      throw new Error(err instanceof ApiError ? err.message : `${DELETE_META[kind].noun}ni o'chirib bo'lmadi`);
    }
    if (kind === 'building') {
      setBuildings((prev) => prev.filter((b) => b.id !== item.id));
      // Bino o'chsa kafedralar QOLADI, lekin binosiz bo'ladi (tasdiq oynasida
      // shunday yozilgan). Mahalliy ro'yxatda eski bino nomi turib qolsa,
      // "Kafedralar" tabi o'chirilgan binoni ko'rsatib turardi.
      setDepartments((prev) => prev.map((d) => (d.buildingId === item.id ? { ...d, buildingId: null, buildingName: '' } : d)));
    }
    if (kind === 'faculty') {
      setFaculties((prev) => prev.filter((f) => f.id !== item.id));
      // Backendda student_groups.faculty_id ondelete="CASCADE" — fakultet
      // bilan uning guruhlari ham o'chadi. Tasdiq oynasi buni aytadi, lekin
      // mahalliy ro'yxat yangilanmasdi: "Guruhlar" tabida allaqachon
      // o'chgan guruhlar ko'rinib turardi (va fakultet sanoqlarida sanalardi).
      setGroups((prev) => prev.filter((g) => g.faculty !== item.name));
    }
    if (kind === 'group') setGroups((prev) => prev.filter((g) => g.id !== item.id));
    if (kind === 'department') setDepartments((prev) => prev.filter((d) => d.id !== item.id));
    toast.success(`«${item.name}» o'chirildi`);
    setDeleteTarget(null);
  }

  function deleteButton(target: DeleteTarget) {
    return <IconButton icon={Trash2} label={`«${target.item.name}» — o'chirish`} size="sm" variant="danger" onClick={() => setDeleteTarget(target)} />;
  }

  const buildingColumns: DataTableColumn<Building>[] = [
    {
      key: 'name',
      header: 'Korpus',
      cell: (b) => <NameCell name={b.name} />,
      sortValue: (b) => b.sortOrder ?? b.name,
    },
    {
      key: 'floors',
      header: 'Qavatlar',
      align: 'right',
      cell: (b) => <Count value={b.floors ?? null} />,
      sortValue: (b) => b.floors ?? null,
      sortFirst: 'desc',
    },
    {
      key: 'cameras',
      header: 'Kameralar',
      align: 'right',
      cell: (b) => <Count value={b.cameraCount} />,
      sortValue: (b) => b.cameraCount,
      sortFirst: 'desc',
    },
    ...(canEdit
      ? [
          {
            key: 'actions',
            header: <span className="sr-only">Amallar</span>,
            align: 'right' as const,
            width: '6rem',
            mobileLabel: 'Amallar',
            cell: (b: Building) => (
              <RowActions>
                <IconButton icon={Pencil} label={`«${b.name}» — tahrirlash`} size="sm" onClick={() => setEditingBuilding(b)} />
                {deleteButton({ kind: 'building', item: b })}
              </RowActions>
            ),
          },
        ]
      : []),
  ];

  const facultyColumns: DataTableColumn<Faculty>[] = [
    { key: 'name', header: 'Fakultet', cell: (f) => <NameCell name={f.name} />, sortValue: (f) => f.name },
    { key: 'courses', header: 'Kurslar', align: 'right', cell: (f) => <Count value={f.courseCount} />, sortValue: (f) => f.courseCount, sortFirst: 'desc' },
    {
      key: 'groups',
      header: 'Guruhlar',
      align: 'right',
      cell: (f) => <Count value={groups.filter((g) => g.faculty === f.name).length} />,
      sortValue: (f) => groups.filter((g) => g.faculty === f.name).length,
      sortFirst: 'desc',
      hideOnMobile: true,
    },
    { key: 'students', header: 'Talabalar', align: 'right', cell: (f) => <Count value={f.studentCount} />, sortValue: (f) => f.studentCount, sortFirst: 'desc' },
  ];

  const groupColumns: DataTableColumn<StudentGroup>[] = [
    { key: 'name', header: 'Guruh', cell: (g) => <NameCell name={g.name} />, sortValue: (g) => g.name },
    {
      key: 'faculty',
      header: 'Fakultet',
      cell: (g) => <span className="text-[13px] text-muted">{g.faculty || <span className="text-subtle">—</span>}</span>,
      sortValue: (g) => g.faculty,
    },
    { key: 'course', header: 'Kurs', width: '5rem', mono: true, cell: (g) => <CodeText className="text-[12px] text-fg">{g.course}-kurs</CodeText>, sortValue: (g) => g.course },
    { key: 'students', header: 'Talabalar', align: 'right', cell: (g) => <Count value={g.studentCount} />, sortValue: (g) => g.studentCount, sortFirst: 'desc' },
  ];

  const departmentColumns: DataTableColumn<Department>[] = [
    { key: 'name', header: 'Kafedra', cell: (d) => <NameCell name={d.name} />, sortValue: (d) => d.name },
    {
      key: 'building',
      header: 'Bino',
      cell: (d) =>
        d.buildingName ? (
          <span className="block min-w-0 truncate text-[13px] text-muted">{d.buildingName}</span>
        ) : (
          <StatusLamp status="warn" label="Binosiz" />
        ),
      sortValue: (d) => d.buildingName || null,
    },
    { key: 'cameras', header: 'Kameralar', align: 'right', cell: (d) => <Count value={d.cameraCount} />, sortValue: (d) => d.cameraCount, sortFirst: 'desc' },
  ];

  const treeColumns: DataTableColumn<OrgNode>[] = [
    {
      key: 'name',
      header: "Bo'linma",
      cell: (n) => (
        <span className="block min-w-0 truncate" style={{ paddingLeft: `${(query ? 0 : n.depth) * 1.1}rem` }}>
          <span className={n.depth === 0 ? 'font-semibold text-fg' : 'text-fg'}>{n.name}</span>
        </span>
      ),
    },
    { key: 'kind', header: 'Turi', width: '9rem', hideOnMobile: true, cell: (n) => <MicroLabel>{n.kindLabel}</MicroLabel> },
    { key: 'total', header: 'Xodimlar', align: 'right', width: '6rem', cell: (n) => <Count value={n.total} /> },
    {
      key: 'present',
      header: 'Keldi',
      align: 'right',
      width: '5rem',
      cell: (n) => <CodeText className="text-[12px] text-success">{n.present}</CodeText>,
    },
    {
      key: 'absent',
      header: 'Kelmadi',
      align: 'right',
      width: '5.5rem',
      cell: (n) => <CodeText className="text-[12px] text-danger">{n.absent}</CodeText>,
    },
    {
      key: 'notYet',
      header: 'Kutilmoqda',
      align: 'right',
      width: '6.5rem',
      hideOnMobile: true,
      cell: (n) => <CodeText className="text-[12px] text-warning">{n.notYet}</CodeText>,
    },
    {
      key: 'noData',
      header: "Ma'lumot yo'q",
      align: 'right',
      width: '7rem',
      hideOnMobile: true,
      cell: (n) => <CodeText className="text-[12px] text-muted">{n.noData}</CodeText>,
    },
  ];

  const searchPlaceholder: Record<TabId, string> = {
    hemis: "Bo'linma…",
    binolar: 'Korpus…',
    fakultetlar: 'Fakultet…',
    guruhlar: 'Guruh…',
    kafedralar: 'Kafedra yoki bino…',
  };

  const isGroups = tab === 'guruhlar';
  const filterFields: FilterFieldEntry[] = [
    { kind: 'search', value: search, onChange: setSearch, placeholder: searchPlaceholder[tab] },
    // Fakultet/kurs faqat "Guruhlar" tabida — boshqa tabda sanalmaydi ham.
    isGroups && {
      kind: 'select',
      value: facultyFilter,
      onChange: setFacultyFilter,
      placeholder: 'Barcha fakultetlar',
      ariaLabel: 'Fakultet',
      options: faculties.map((f) => ({ value: f.name, label: f.name })),
    },
    isGroups && {
      kind: 'select',
      value: courseFilter,
      onChange: setCourseFilter,
      placeholder: 'Barcha kurslar',
      ariaLabel: 'Kurs',
      options: courseOptions,
    },
  ];
  // Bo'sh holat matni ham xuddi shu sanoqqa tayanadi (ilgari alohida
  // hisoblanardi va qidiruvdagi bo'sh probelni boshqacha sanardi).
  const filtersActive = filterActiveCount(filterFields);
  const toolbar = (
    <FilterBar
      fields={filterFields}
      onReset={() => {
        setSearch('');
        setFacultyFilter('');
        setCourseFilter('');
      }}
    />
  );

  // "Guruhlar" tabida fakultet/kurs filtri ham bor: filtr tufayli ro'yxat
  // bo'sh bo'lsa "Guruh qo'shish" tugmasi noto'g'ri maslahat bo'ladi.
  const emptyAction = (id: TabId) =>
    canEdit && id === 'binolar' && !query ? (
      <Button icon={Plus} variant="primary" onClick={() => setAddOpen(id)}>
        {ADD_LABEL[id]}
      </Button>
    ) : undefined;

  const common = { loading, loadingRows: 5, dense: true, maxHeight: 'none' } as const;

  const shownTree = (tree ?? []).filter((node) => matches(node.name, query));
  const SECTION: Record<TabId, { title: string; shown: number; total: number }> = {
    hemis: { title: "Bo'linmalar", shown: shownTree.length, total: tree?.length ?? 0 },
    binolar: { title: 'Korpuslar', shown: shownBuildings.length, total: buildings.length },
    fakultetlar: { title: 'Fakultetlar', shown: shownFaculties.length, total: faculties.length },
    guruhlar: { title: 'Guruhlar', shown: shownGroups.length, total: groups.length },
    kafedralar: { title: 'Kafedralar', shown: shownDepartments.length, total: departments.length },
  };
  const section = SECTION[tab];

  const sectionRight = (
    <MicroLabel>{loading ? 'Yuklanmoqda' : `${formatNumber(section.shown)} / ${formatNumber(section.total)} ta`}</MicroLabel>
  );

  return (
    <Page
      title="Tashkiliy tuzilma"
      tabs={tabs}
      actions={
        tab === 'hemis' ? (
          <PdfButton path="/api/situation/pdf/tuzilma" params={{}} filename="tuzilma.pdf" />
        ) : canEdit && tab === 'binolar' && (
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => setAddOpen(tab)}
            disabled={loading || error !== null}
            title={error ? 'Tuzilma yuklanmadi' : loading ? 'Yuklanmoqda…' : undefined}
          >
            {ADD_LABEL[tab]}
          </Button>
        )
      }
      toolbar={error ? undefined : toolbar}
    >
      {error ? (
        <ErrorState variant="block" message={error} onRetry={reload} className="border border-border bg-surface" />
      ) : (
        <>
          {tab === 'hemis' && (
            <IntelPanel title={section.title} right={sectionRight}>
              {treeError ? (
                <ErrorState message={treeError} onRetry={reload} />
              ) : (
                <DataTable
                  {...common}
                  loading={tree === null}
                  ariaLabel="HEMIS tuzilmasi"
                  columns={treeColumns}
                  rows={query ? shownTree : tree ?? []}
                  rowKey={(n) => n.id}
                  onRowClick={canOpenAttendance ? (n) => n.total > 0 && navigate(situationPaths.kafedra(n.id)) : undefined}
                  emptyTitle={query ? "Bo'linma topilmadi" : "HEMIS tuzilmasi hali kelmagan"}
                  manualSort
                />
              )}
            </IntelPanel>
          )}

          {(tab === 'fakultetlar' || tab === 'guruhlar' || tab === 'kafedralar') && (
            <p className="border border-border bg-surface-2 px-3 py-2 text-[12px] text-muted">
              Bu ro'yxat HEMIS'dan avtomatik yangilanadi — qo'shish va o'chirish HEMIS'ning o'zida qilinadi.
            </p>
          )}

          {tab === 'binolar' && (
            <IntelPanel title={section.title} right={sectionRight}>
            <DataTable
              {...common}
              ariaLabel="Korpuslar"
              columns={buildingColumns}
              rows={shownBuildings}
              rowKey={(b) => b.id}
              defaultSort={{ key: 'name', dir: 'asc' }}
              emptyTitle={query ? 'Korpus topilmadi' : "Korpus qo'shilmagan"}
              emptyAction={emptyAction('binolar')}
            />
            </IntelPanel>
          )}

          {tab === 'fakultetlar' && (
            <IntelPanel title={section.title} right={sectionRight}>
            <DataTable
              {...common}
              ariaLabel="Fakultetlar"
              columns={facultyColumns}
              rows={shownFaculties}
              rowKey={(f) => f.id}
              onRowClick={canOpenAttendance ? (f) => navigate(situationPaths.faculty(f.id)) : undefined}
              defaultSort={{ key: 'name', dir: 'asc' }}
              emptyTitle={query ? 'Fakultet topilmadi' : "Fakultet qo'shilmagan"}
              emptyAction={emptyAction('fakultetlar')}
            />
            </IntelPanel>
          )}

          {tab === 'guruhlar' && (
            <IntelPanel title={section.title} right={sectionRight}>
            <DataTable
              {...common}
              ariaLabel="Guruhlar"
              columns={groupColumns}
              rows={shownGroups}
              rowKey={(g) => g.id}
              onRowClick={canOpenAttendance ? (g) => navigate(situationPaths.group(g.name)) : undefined}
              defaultSort={{ key: 'name', dir: 'asc' }}
              emptyTitle={filtersActive ? 'Guruh topilmadi' : "Guruh qo'shilmagan"}
              emptyAction={emptyAction('guruhlar')}
            />
            </IntelPanel>
          )}

          {tab === 'kafedralar' && (
            <>
              <IntelPanel title={section.title} right={sectionRight}>
              <DataTable
                {...common}
                ariaLabel="Kafedralar"
                columns={departmentColumns}
                rows={shownDepartments}
                rowKey={(d) => d.id}
                onRowClick={canOpenAttendance ? (d) => navigate(situationPaths.kafedra(d.id)) : undefined}
                defaultSort={{ key: 'name', dir: 'asc' }}
                emptyTitle={query ? 'Kafedra topilmadi' : "Kafedra qo'shilmagan"}
                emptyAction={emptyAction('kafedralar')}
              />
              </IntelPanel>
            </>
          )}
        </>
      )}

      <AddBuildingModal
        open={addOpen === 'binolar'}
        onClose={() => setAddOpen(null)}
        onSave={(building) => {
          setBuildings((prev) => [...prev, building]);
          toast.success(`«${building.name}» qo'shildi`);
        }}
      />
      <AddBuildingModal
        open={!!editingBuilding}
        building={editingBuilding}
        onClose={() => setEditingBuilding(null)}
        onSave={(building) => {
          setBuildings((prev) => prev.map((b) => (b.id === building.id ? building : b)));
          setEditingBuilding(null);
          toast.success('Saqlandi');
        }}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        title={deleteTarget ? `${capitalize(DELETE_META[deleteTarget.kind].noun)}ni o'chirasizmi?` : ''}
        message={
          deleteTarget &&
          (() => {
            const { lost, kept } = deleteConsequences(
              deleteTarget,
              deleteTarget.kind === 'faculty' ? groups.filter((g) => g.faculty === deleteTarget.item.name).length : 0,
            );
            return (
              <div className="flex flex-col gap-2">
                <p>
                  <span className="font-medium text-fg">«{deleteTarget.item.name}»</span> butunlay o&apos;chiriladi.
                </p>
                <p className="font-medium text-danger">Birga o&apos;chadi:</p>
                <ul className="list-disc space-y-0.5 pl-5">
                  {lost.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <p className="font-medium text-fg">Saqlanib qoladi:</p>
                <ul className="list-disc space-y-0.5 pl-5">
                  {kept.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            );
          })()
        }
        confirmLabel="O'chirish"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </Page>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
