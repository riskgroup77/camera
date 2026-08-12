import { useEffect, useMemo, useState } from 'react';
import { Loader2, Settings2 } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import Badge from '../../components/Badge';
import AiModuleModal from '../../components/admin/AiModuleModal';
import { api } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { AI_MODULE_GROUP_LABELS } from '../../mock/admin';
import type { AIModule, AIModuleGroup } from '../../types';

const GROUPS = Object.keys(AI_MODULE_GROUP_LABELS) as AIModuleGroup[];

export default function AIModulesPage() {
  const { role, token } = useAuth();
  const { can } = usePermissions();
  const canConfigure = can('configureAi', role);

  const [modules, setModules] = useState<AIModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeGroup, setActiveGroup] = useState<AIModuleGroup>('A');
  const [editing, setEditing] = useState<AIModule | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<AIModule[]>('/api/ai-modules', token)
      .then((res) => {
        if (!cancelled) {
          setModules(res);
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
  }, [token]);

  const activeCount = modules.filter((m) => m.active).length;

  const byGroup = useMemo(() => {
    const map = new Map<AIModuleGroup, AIModule[]>();
    for (const g of GROUPS) map.set(g, []);
    for (const m of modules) map.get(m.group)?.push(m);
    return map;
  }, [modules]);

  function openEdit(m: AIModule) {
    setEditing(m);
  }

  function handleSave(saved: AIModule) {
    setModules((prev) => prev.map((m) => (m.id === saved.id ? saved : m)));
    setEditing(null);
  }

  const currentModules = byGroup.get(activeGroup) ?? [];

  return (
    <section className="glass p-6">
      <PageHeader
        title="AI Modullari"
        subtitle={`Texnik topshiriq 3-bo'lim — ${modules.length} ta AI kriteriya (A-F toifalar)`}
        action={<Badge tone="indigo">{`${activeCount} / ${modules.length} faol`}</Badge>}
      />

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-5 flex flex-wrap gap-2 border-b border-white/70 dark:border-white/10 text-sm">
        {GROUPS.map((g) => {
          const groupModules = byGroup.get(g) ?? [];
          const groupActive = groupModules.filter((m) => m.active).length;
          return (
            <button
              key={g}
              onClick={() => setActiveGroup(g)}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 font-medium transition-colors ${
                activeGroup === g
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-md bg-slate-100 dark:bg-white/5 text-[11px] font-bold">
                {g}
              </span>
              <span className="hidden sm:inline">{AI_MODULE_GROUP_LABELS[g]}</span>
              <span className="text-xs text-slate-400 dark:text-slate-500">
                ({groupActive}/{groupModules.length})
              </span>
            </button>
          );
        })}
      </div>

      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">{AI_MODULE_GROUP_LABELS[activeGroup]}</p>

      {loading && modules.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/70 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-white/50 dark:bg-white/5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <th className="px-4 py-3">№</th>
                <th className="px-4 py-3">Kriteriya</th>
                <th className="px-4 py-3">Aniqlash usuli / AI model</th>
                <th className="px-4 py-3">Holat</th>
                <th className="px-4 py-3">Aniqlik</th>
                <th className="px-4 py-3">Kamera</th>
                <th className="px-4 py-3">Amallar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/60 dark:divide-white/5">
              {currentModules.map((m) => (
                <tr key={m.id} className="transition-colors hover:bg-white/40 dark:hover:bg-white/5">
                  <td className="px-4 py-3 text-slate-400 dark:text-slate-500">{m.code || '—'}</td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{m.name}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">{m.description}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{m.method}</td>
                  <td className="px-4 py-3">
                    <Badge tone={m.active ? 'green' : 'slate'}>{m.active ? 'Faol' : 'Nofaol'}</Badge>
                  </td>
                  <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">
                    {m.active ? `${m.accuracy}%` : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{m.cameraCount || '—'}</td>
                  <td className="px-4 py-3">
                    {canConfigure ? (
                      <button
                        onClick={() => openEdit(m)}
                        className="flex items-center gap-1 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                      >
                        <Settings2 size={12} />
                        Sozlash
                      </button>
                    ) : (
                      <span className="text-xs text-slate-300 dark:text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <AiModuleModal open={!!editing} onClose={() => setEditing(null)} module={editing} onSave={handleSave} />
    </section>
  );
}
