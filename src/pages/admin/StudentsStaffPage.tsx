import { useState } from 'react';
import { Loader2, Plus, Search } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import AddStudentStaffModal from '../../components/admin/AddStudentStaffModal';
import EditStudentStaffModal from '../../components/admin/EditStudentStaffModal';
import { useServerPage } from '../../lib/useServerPage';
import { useFaculties } from '../../lib/useFaculties';
import type { StudentStaffRecord } from '../../types';

const BIOMETRICS_TONE: Record<StudentStaffRecord['biometricsStatus'], 'green' | 'amber' | 'slate'> = {
  tasdiqlangan: 'green',
  kutilmoqda: 'amber',
  yoq: 'slate',
};

const BIOMETRICS_LABEL: Record<StudentStaffRecord['biometricsStatus'], string> = {
  tasdiqlangan: 'Tasdiqlangan',
  kutilmoqda: 'Kutilmoqda',
  yoq: "Yo'q",
};

const TYPE_FILTERS = ['Barchasi', 'Talaba', 'Xodim'] as const;

export default function StudentsStaffPage() {
  const { faculties } = useFaculties();
  const facultyFilters = ['Barcha fakultet', ...faculties.map((f) => f.name)];

  const [typeFilter, setTypeFilter] = useState<(typeof TYPE_FILTERS)[number]>('Barchasi');
  const [facultyFilter, setFacultyFilter] = useState('Barcha fakultet');
  const [search, setSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<StudentStaffRecord | null>(null);

  const {
    items: records,
    page,
    setPage,
    totalPages,
    total,
    pageSize,
    loading,
    error,
    reload,
  } = useServerPage<StudentStaffRecord>(
    '/api/students-staff',
    {
      type: typeFilter === 'Barchasi' ? undefined : typeFilter === 'Talaba' ? 'talaba' : 'xodim',
      faculty: facultyFilter === 'Barcha fakultet' ? undefined : facultyFilter,
      search: search.trim() || undefined,
    },
    10,
  );

  return (
    <section className="glass p-6">
      <PageHeader
        title="Talabalar va Xodimlar"
        subtitle="Shaxsiy ma'lumotlar va biometriya boshqaruvi"
        action={
          <button
            onClick={() => setModalOpen(true)}
            className="btn-glass flex items-center gap-1.5 !bg-indigo-600 !text-white hover:!bg-indigo-700"
          >
            <Plus size={14} />
            Yangi biriktirish
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="F.I.Sh. bo'yicha qidiruv..."
            aria-label="Talabalar va xodimlarni qidirish"
            className="w-full rounded-xl border border-white/80 bg-white/60 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:placeholder:text-slate-500"
          />
        </div>

        <div className="flex flex-wrap gap-2 text-sm">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setTypeFilter(f)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                typeFilter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
              }`}
            >
              {f}
            </button>
          ))}
          <span className="mx-1 w-px self-stretch bg-white/80 dark:bg-white/10" />
          {facultyFilters.map((f) => (
            <button
              key={f}
              onClick={() => setFacultyFilter(f)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                facultyFilter === f ? 'bg-indigo-600 text-white' : 'bg-white/60 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-white/90 dark:hover:bg-white/10'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      {loading && records.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : records.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
          Filtrlarga mos yozuv topilmadi
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <th className="px-4 py-3">Rasm / Face-ID</th>
                <th className="px-4 py-3">F.I.Sh.</th>
                <th className="px-4 py-3">Turi</th>
                <th className="px-4 py-3">Fakultet</th>
                <th className="px-4 py-3">Guruh / Lavozim</th>
                <th className="px-4 py-3">Biometriya holati</th>
                <th className="px-4 py-3">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {records.map((s) => (
                <tr key={s.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="px-4 py-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-100 dark:bg-indigo-500/15 text-xs font-bold text-indigo-600">
                      {s.initials}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">{s.fullName}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {s.type === 'talaba' ? 'Talaba' : 'Xodim'}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{s.faculty}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{s.groupOrPosition}</td>
                  <td className="px-4 py-3">
                    <Badge tone={BIOMETRICS_TONE[s.biometricsStatus]}>
                      {BIOMETRICS_LABEL[s.biometricsStatus]}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-indigo-600 dark:text-indigo-400">
                    <button
                      onClick={() => setEditing(s)}
                      className="text-xs font-semibold hover:underline"
                    >
                      Tahrirlash
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4">
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onChange={setPage} />
          </div>
        </div>
      )}

      <AddStudentStaffModal open={modalOpen} onClose={() => setModalOpen(false)} onAdd={() => reload()} />
      <EditStudentStaffModal
        record={editing}
        onClose={() => setEditing(null)}
        onSave={() => {
          setEditing(null);
          reload();
        }}
      />
    </section>
  );
}
