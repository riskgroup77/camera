import { useEffect, useState } from 'react';
import { BookOpen, Building2, Camera, Loader2, Pencil, Plus, Trash2, Users2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import AddBuildingModal from '../../components/admin/AddBuildingModal';
import AddFacultyModal from '../../components/admin/AddFacultyModal';
import AddGroupModal from '../../components/admin/AddGroupModal';
import { ApiError, api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { Building, Faculty, StudentGroup } from '../../types';

const TABS = ["O'quv korpuslari", 'Fakultetlar va Kurslar', "Guruhlar ro'yxati"] as const;

export default function OrgStructurePage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [faculties, setFaculties] = useState<Faculty[]>([]);
  const [groups, setGroups] = useState<StudentGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [buildingModalOpen, setBuildingModalOpen] = useState(false);
  const [editingBuilding, setEditingBuilding] = useState<Building | null>(null);
  const [facultyModalOpen, setFacultyModalOpen] = useState(false);
  const [groupModalOpen, setGroupModalOpen] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.get<Building[]>('/api/buildings', token),
      api.get<Faculty[]>('/api/faculties', token),
      api.get<StudentGroup[]>('/api/student-groups', token),
    ])
      .then(([b, f, g]) => {
        if (cancelled) return;
        setBuildings(b);
        setFaculties(f);
        setGroups(g);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleDeleteBuilding(id: string) {
    try {
      await api.del(`/api/buildings/${id}`, token);
      setBuildings((prev) => prev.filter((b) => b.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Binoni o'chirib bo'lmadi");
    }
  }

  async function handleDeleteFaculty(id: string) {
    try {
      await api.del(`/api/faculties/${id}`, token);
      setFaculties((prev) => prev.filter((f) => f.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Fakultetni o'chirib bo'lmadi");
    }
  }

  async function handleDeleteGroup(id: string) {
    try {
      await api.del(`/api/student-groups/${id}`, token);
      setGroups((prev) => prev.filter((g) => g.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Guruhni o'chirib bo'lmadi");
    }
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Tashkiliy tuzilma"
        subtitle="Binolar, fakultetlar, kurslar va guruhlar boshqaruvi"
      />

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-5 flex gap-2 border-b border-white/70 dark:border-white/10 text-sm">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 font-medium transition-colors ${
              tab === t
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <>
          {tab === "O'quv korpuslari" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {buildings.map((b) => (
                <div key={b.id} className="glass-deep flex flex-col gap-3 p-5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100 dark:bg-indigo-500/15 text-indigo-600">
                    <Building2 size={18} />
                  </div>
                  <div>
                    <p className="font-bold text-slate-900 dark:text-slate-100">{b.name}</p>
                    <p className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                      <Camera size={12} />
                      {b.cameraCount} ta kamera biriktirilgan
                    </p>
                  </div>
                  <div className="flex gap-3 border-t border-white/70 dark:border-white/10 pt-3 text-xs font-semibold">
                    <button
                      onClick={() => setEditingBuilding(b)}
                      className="flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline"
                    >
                      <Pencil size={12} />
                      Tahrirlash
                    </button>
                    <button
                      onClick={() => handleDeleteBuilding(b.id)}
                      className="flex items-center gap-1 text-red-500 dark:text-red-400 hover:underline"
                    >
                      <Trash2 size={12} />
                      O'chirish
                    </button>
                  </div>
                </div>
              ))}

              <button
                onClick={() => setBuildingModalOpen(true)}
                className="glass-deep flex min-h-[140px] flex-col items-center justify-center gap-2 border-dashed text-sm font-semibold text-slate-500 dark:text-slate-400 transition-colors hover:text-indigo-600 dark:hover:text-indigo-400"
              >
                <Plus size={20} />
                Yangi korpus qo'shish
              </button>
            </div>
          )}

          {tab === 'Fakultetlar va Kurslar' && (
            <div className="space-y-4">
              <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      <th className="px-4 py-3">Fakultet</th>
                      <th className="px-4 py-3">Kurslar soni</th>
                      <th className="px-4 py-3">Talabalar soni</th>
                      <th className="px-4 py-3">Amallar</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/60 dark:divide-white/5">
                    {faculties.map((f) => (
                      <tr key={f.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                        <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                          <span className="flex items-center gap-2">
                            <BookOpen size={14} className="text-indigo-500" />
                            {f.name}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{f.courseCount}</td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                          {f.studentCount.toLocaleString('ru-RU')}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleDeleteFaculty(f.id)}
                            className="flex items-center gap-1 text-xs font-semibold text-red-500 dark:text-red-400 hover:underline"
                          >
                            <Trash2 size={12} />
                            O'chirish
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => setFacultyModalOpen(true)}
                className="btn-glass flex items-center gap-1.5"
              >
                <Plus size={14} />
                Yangi fakultet qo'shish
              </button>
            </div>
          )}

          {tab === "Guruhlar ro'yxati" && (
            <div className="space-y-4">
              <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      <th className="px-4 py-3">Guruh</th>
                      <th className="px-4 py-3">Fakultet</th>
                      <th className="px-4 py-3">Kurs</th>
                      <th className="px-4 py-3">Talabalar soni</th>
                      <th className="px-4 py-3">Amallar</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/60 dark:divide-white/5">
                    {groups.map((g) => (
                      <tr key={g.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                        <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                          <span className="flex items-center gap-2">
                            <Users2 size={14} className="text-indigo-500" />
                            {g.name}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{g.faculty}</td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{g.course}-kurs</td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{g.studentCount}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleDeleteGroup(g.id)}
                            className="flex items-center gap-1 text-xs font-semibold text-red-500 dark:text-red-400 hover:underline"
                          >
                            <Trash2 size={12} />
                            O'chirish
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => setGroupModalOpen(true)}
                className="btn-glass flex items-center gap-1.5"
              >
                <Plus size={14} />
                Yangi guruh qo'shish
              </button>
            </div>
          )}
        </>
      )}

      <AddBuildingModal
        open={buildingModalOpen}
        onClose={() => setBuildingModalOpen(false)}
        onSave={(building) => setBuildings((prev) => [...prev, building])}
      />
      <AddBuildingModal
        open={!!editingBuilding}
        building={editingBuilding}
        onClose={() => setEditingBuilding(null)}
        onSave={(building) => {
          setBuildings((prev) => prev.map((b) => (b.id === building.id ? building : b)));
          setEditingBuilding(null);
        }}
      />
      <AddFacultyModal
        open={facultyModalOpen}
        onClose={() => setFacultyModalOpen(false)}
        onAdd={(faculty) => setFaculties((prev) => [...prev, faculty])}
      />
      <AddGroupModal
        open={groupModalOpen}
        faculties={faculties}
        onClose={() => setGroupModalOpen(false)}
        onAdd={(group) => setGroups((prev) => [...prev, group])}
      />
    </section>
  );
}
