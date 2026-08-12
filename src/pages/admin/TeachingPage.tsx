import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Brain, Loader2, Moon, Presentation, Timer, Trash2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import Badge from '../../components/Badge';
import ConfirmDialog from '../../components/ConfirmDialog';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import type { LessonSession } from '../../types';

const AXIS_COLOR = '#94a3b8';
const GRID_COLOR = 'rgba(148,163,184,0.25)';

export default function TeachingPage() {
  const { token } = useAuth();
  const [sessions, setSessions] = useState<LessonSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [groupFilter, setGroupFilter] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<LessonSession | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<{ items: LessonSession[] }>('/api/lesson-sessions?pageSize=200', token)
      .then((res) => {
        if (!cancelled) {
          setSessions(res.items);
          setError(null);
        }
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
  }, [token, reloadKey]);

  async function handleDelete() {
    if (!deleting) return;
    await api.del(`/api/lesson-sessions/${deleting.id}`, token);
    setDeleting(null);
    setReloadKey((k) => k + 1);
  }

  const groups = useMemo(() => Array.from(new Set(sessions.map((s) => s.group))), [sessions]);

  const filtered = useMemo(
    () => (groupFilter ? sessions.filter((s) => s.group === groupFilter) : sessions),
    [sessions, groupFilter],
  );

  const stats = useMemo(() => {
    if (!filtered.length) return { attention: 0, sleep: 0, activity: 0, onTime: 0 };
    const attention = Math.round(
      filtered.reduce((sum, s) => sum + s.attentionScore, 0) / filtered.length,
    );
    const activity = Math.round(
      filtered.reduce((sum, s) => sum + s.teacherActivityScore, 0) / filtered.length,
    );
    const sleep = filtered.reduce((sum, s) => sum + s.sleepIncidents, 0);
    const onTime = Math.round(
      (filtered.filter((s) => s.teacherOnTime).length / filtered.length) * 100,
    );
    return { attention, sleep, activity, onTime };
  }, [filtered]);

  const trendData = useMemo(() => {
    const byDate = new Map<string, { date: string; total: number; count: number }>();
    for (const s of filtered) {
      const entry = byDate.get(s.date) ?? { date: s.date, total: 0, count: 0 };
      entry.total += s.attentionScore;
      entry.count += 1;
      byDate.set(s.date, entry);
    }
    return Array.from(byDate.values())
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((e) => ({ date: e.date.slice(5), diqqat: Math.round(e.total / e.count) }));
  }, [filtered]);

  const teacherData = useMemo(() => {
    const byTeacher = new Map<string, { teacher: string; total: number; count: number }>();
    for (const s of filtered) {
      const entry = byTeacher.get(s.teacher) ?? { teacher: s.teacher, total: 0, count: 0 };
      entry.total += s.teacherActivityScore;
      entry.count += 1;
      byTeacher.set(s.teacher, entry);
    }
    return Array.from(byTeacher.values()).map((e) => ({
      teacher: e.teacher.replace(/^(Prof\.|Dots\.)\s*/, ''),
      faollik: Math.round(e.total / e.count),
    }));
  }, [filtered]);

  return (
    <section className="glass p-6">
      <PageHeader
        title="Dars monitoring paneli"
        subtitle="Talaba diqqati va o'qituvchi faolligi bo'yicha tahlil (TT 3-E bo'limi)"
        action={
          <div className="flex flex-wrap gap-2 text-sm">
            <button
              onClick={() => setGroupFilter(null)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                !groupFilter ? 'bg-indigo-600 text-white' : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300'
              }`}
            >
              Barcha guruhlar
            </button>
            {groups.map((g) => (
              <button
                key={g}
                onClick={() => setGroupFilter(g)}
                className={`rounded-lg px-3 py-1.5 font-medium transition-colors ${
                  groupFilter === g ? 'bg-indigo-600 text-white' : 'bg-white/60 text-slate-600 hover:bg-white/90 dark:bg-white/5 dark:text-slate-300'
                }`}
              >
                {g}
              </button>
            ))}
          </div>
        }
      />

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard icon={<Brain size={20} />} value={`${stats.attention}%`} label="O'rtacha diqqat" tone="indigo" />
        <StatCard icon={<Moon size={20} />} value={stats.sleep} label="Uxlash holatlari" tone="amber" />
        <StatCard icon={<Presentation size={20} />} value={`${stats.activity}%`} label="O'qituvchi faolligi" tone="green" />
        <StatCard icon={<Timer size={20} />} value={`${stats.onTime}%`} label="Vaqtida kelish" tone="indigo" />
      </div>

      {loading && sessions.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="glass-deep p-4">
              <h3 className="mb-3 text-sm font-bold text-slate-800 dark:text-slate-200">
                Diqqat balli trendi
              </h3>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData}>
                    <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                    <XAxis dataKey="date" tick={{ fill: AXIS_COLOR, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      width={30}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: 'none', fontSize: 12 }}
                      formatter={(v) => [`${v}%`, 'Diqqat']}
                    />
                    <Line type="monotone" dataKey="diqqat" stroke="#6366f1" strokeWidth={2.5} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="glass-deep p-4">
              <h3 className="mb-3 text-sm font-bold text-slate-800 dark:text-slate-200">
                O'qituvchilar bo'yicha faollik
              </h3>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={teacherData} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid stroke={GRID_COLOR} horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tick={{ fill: AXIS_COLOR, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis
                      type="category"
                      dataKey="teacher"
                      tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      width={90}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: 'none', fontSize: 12 }}
                      formatter={(v) => [`${v}%`, 'Faollik']}
                    />
                    <Bar dataKey="faollik" fill="#22c55e" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {filtered.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 dark:border-white/10 p-10 text-center text-sm text-slate-400 dark:text-slate-500">
              Hali dars monitoring yozuvlari yo'q
            </p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="bg-white/50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-white/5 dark:text-slate-400">
                    <th className="px-4 py-3">Sana</th>
                    <th className="px-4 py-3">Guruh</th>
                    <th className="px-4 py-3">Fan</th>
                    <th className="px-4 py-3">O'qituvchi</th>
                    <th className="px-4 py-3">Diqqat</th>
                    <th className="px-4 py-3">Uxlash</th>
                    <th className="px-4 py-3">Faollik</th>
                    <th className="px-4 py-3">Vaqtida</th>
                    <th className="px-4 py-3">Amallar</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/60 dark:divide-white/5">
                  {filtered.map((s) => (
                    <tr key={s.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                        {s.date}
                      </td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{s.group}</td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{s.subject}</td>
                      <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{s.teacher}</td>
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">
                        {s.attentionScore}%
                      </td>
                      <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{s.sleepIncidents}</td>
                      <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">
                        {s.teacherActivityScore}%
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={s.teacherOnTime ? 'green' : 'amber'}>
                          {s.teacherOnTime ? 'Ha' : "Yo'q"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setDeleting(s)}
                          title="O'chirish"
                          className="text-slate-400 transition-colors hover:text-red-600 dark:text-slate-500 dark:hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Dars monitoring yozuvini o'chirish"
        message={deleting ? `${deleting.group} / ${deleting.subject} (${deleting.date}) yozuvini o'chirishni tasdiqlaysizmi? Bu amalni ortga qaytarib bo'lmaydi.` : ''}
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </section>
  );
}
