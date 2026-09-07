import { useCallback, useEffect, useState } from 'react';
import { Download, Loader2, Plus, ScanFace, Search } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import Badge from '../../components/Badge';
import Pagination from '../../components/Pagination';
import AddStudentStaffModal from '../../components/admin/AddStudentStaffModal';
import EditStudentStaffModal from '../../components/admin/EditStudentStaffModal';
import { useServerPage } from '../../lib/useServerPage';
import { useFaculties } from '../../lib/useFaculties';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { config } from '../../lib/config';
import type { BiometricsCoverage, StudentStaffRecord } from '../../types';

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

/** Yuz holati filtri.
 *
 *  Eng ko'p beriladigan savol — "ro'yxatdagilardan nechtasi yuzini
 *  tasdiqlamadi". Uni ro'yxatni varaqlab sanab bo'lmaydi, shuning uchun
 *  filtr ham, alohida qamrov paneli ham qo'shilgan. */
const BIOMETRICS_FILTERS = [
  { key: '', label: 'Barcha holat' },
  { key: 'tasdiqlangan', label: 'Tasdiqlangan' },
  { key: 'kutilmoqda', label: 'Kutilmoqda' },
  { key: 'yoq', label: 'Tasdiqlanmagan' },
] as const;

/** Fakulteti ko'rsatilmaganlar (rektorat, texnik va xo'jalik bo'limlari).
 *  Bo'sh satr "filtr yo'q" degani, shuning uchun alohida kalit kerak. */
const NO_FACULTY_KEY = '__none__';

export default function StudentsStaffPage() {
  const { faculties } = useFaculties();
  const facultyFilters = ['Barcha fakultet', ...faculties.map((f) => f.name), NO_FACULTY_KEY];

  const { token } = useAuth();
  const [typeFilter, setTypeFilter] = useState<(typeof TYPE_FILTERS)[number]>('Barchasi');
  const [facultyFilter, setFacultyFilter] = useState('Barcha fakultet');
  const [biometricsFilter, setBiometricsFilter] = useState<string>('');
  const [search, setSearch] = useState('');
  const [coverage, setCoverage] = useState<BiometricsCoverage | null>(null);
  const [downloading, setDownloading] = useState(false);
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
      biometricsStatus: biometricsFilter || undefined,
      search: search.trim() || undefined,
    },
    10,
  );

  // Qamrov ro'yxatdan MUSTAQIL yuklanadi: u butun bazani ko'rsatadi,
  // filtrlangan sahifani emas. "Pediatriya bo'yicha filtr qo'yilgan"
  // holatda ham umumiy manzara ko'rinib turishi kerak.
  const loadCoverage = useCallback(() => {
    if (!token) return;
    const type =
      typeFilter === 'Barchasi' ? '' : typeFilter === 'Talaba' ? '?type=talaba' : '?type=xodim';
    api
      .get<BiometricsCoverage>(`/api/students-staff/biometrics-coverage${type}`, token)
      .then(setCoverage)
      .catch(() => setCoverage(null));
  }, [token, typeFilter]);

  useEffect(loadCoverage, [loadCoverage]);

  /** Ekrandagi filtr bilan AYNAN bir xil ro'yxatni CSV qilib yuklaydi. */
  async function downloadCsv() {
    if (!token) return;
    setDownloading(true);
    try {
      const params = new URLSearchParams();
      if (typeFilter !== 'Barchasi') params.set('type', typeFilter === 'Talaba' ? 'talaba' : 'xodim');
      if (facultyFilter !== 'Barcha fakultet') params.set('faculty', facultyFilter);
      if (biometricsFilter) params.set('biometricsStatus', biometricsFilter);
      if (search.trim()) params.set('search', search.trim());

      const res = await fetch(`${config.apiBaseUrl}/api/students-staff/export?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `xodimlar-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Talabalar va Xodimlar"
        subtitle="Shaxsiy ma'lumotlar va biometriya boshqaruvi"
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={downloadCsv}
              disabled={downloading || !token}
              className="btn-glass flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-50"
              title="Ekrandagi filtr bo'yicha ro'yxatni yuklab olish"
            >
              <Download size={14} />
              {downloading ? 'Tayyorlanmoqda...' : 'Yuklab olish'}
            </button>
            <button
              onClick={() => setModalOpen(true)}
              className="btn-glass flex items-center gap-1.5 !bg-indigo-600 !text-white hover:!bg-indigo-700"
            >
              <Plus size={14} />
              Yangi biriktirish
            </button>
          </div>
        }
      />

      {coverage && coverage.total > 0 && (
        <div className="mb-5 rounded-2xl border border-white/70 bg-white/50 p-4 dark:border-white/10 dark:bg-white/5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-bold text-slate-900 dark:text-slate-100">
              <ScanFace size={15} className="text-indigo-500" />
              Yuzni tasdiqlash qamrovi
            </h3>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="text-slate-500 dark:text-slate-400">
                Jami: <span className="font-bold text-slate-800 dark:text-slate-200">{coverage.total}</span>
              </span>
              <span className="text-emerald-600 dark:text-emerald-400">
                Tasdiqlagan: <span className="font-bold">{coverage.confirmed}</span>
              </span>
              <span className="text-red-500 dark:text-red-400">
                Tasdiqlamagan: <span className="font-bold">{coverage.missing + coverage.pending}</span>
              </span>
              <span className="rounded-md bg-indigo-600 px-2 py-0.5 font-bold text-white">
                {coverage.percent === null ? "ma'lumot yo'q" : `${coverage.percent}%`}
              </span>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500">
                  <th className="pb-1.5 pr-3 font-semibold">Fakultet</th>
                  <th className="pb-1.5 pr-3 text-center font-semibold">Jami</th>
                  <th className="pb-1.5 pr-3 text-center font-semibold">Tasdiqlagan</th>
                  <th className="pb-1.5 pr-3 text-center font-semibold">Tasdiqlamagan</th>
                  <th className="pb-1.5 font-semibold">Qamrov</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/60 dark:divide-white/5">
                {coverage.byFaculty.map((row) => {
                  const notConfirmed = row.missing + row.pending;
                  return (
                    <tr key={row.faculty}>
                      <td className="py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-300">{row.faculty}</td>
                      <td className="py-1.5 pr-3 text-center tabular-nums text-slate-600 dark:text-slate-400">
                        {row.total}
                      </td>
                      <td className="py-1.5 pr-3 text-center font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                        {row.confirmed}
                      </td>
                      <td className="py-1.5 pr-3 text-center font-semibold tabular-nums text-red-500 dark:text-red-400">
                        {notConfirmed}
                      </td>
                      <td className="py-1.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                            <div
                              className="h-full rounded-full bg-emerald-500"
                              style={{ width: `${row.percent ?? 0}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-slate-500 dark:text-slate-400">
                            {row.percent === null ? '—' : `${row.percent}%`}
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="F.I.Sh. yoki JSHSHIR bo'yicha qidiruv..."
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
              {f === NO_FACULTY_KEY ? 'Fakultetsiz' : f}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
          Yuz holati
        </span>
        {BIOMETRICS_FILTERS.map((f) => (
          <button
            key={f.key || 'all'}
            onClick={() => setBiometricsFilter(f.key)}
            className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
              biometricsFilter === f.key
                ? 'bg-indigo-600 text-white'
                : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-400 dark:hover:bg-white/10'
            }`}
          >
            {f.label}
          </button>
        ))}
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
