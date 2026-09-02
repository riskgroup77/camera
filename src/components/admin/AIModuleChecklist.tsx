import { AlertCircle, Ban } from 'lucide-react';
import { AI_MODULE_GROUP_LABELS } from '../../lib/aiModuleGroups';
import type { AIModuleGroup, CameraModuleOption } from '../../types';

const GROUPS = Object.keys(AI_MODULE_GROUP_LABELS) as AIModuleGroup[];

export default function AIModuleChecklist({
  modules,
  excluded,
  onToggle,
  onToggleGroup,
  readOnly = false,
}: {
  modules: CameraModuleOption[];
  excluded: Set<number>;
  onToggle: (code: number) => void;
  onToggleGroup?: (group: AIModuleGroup, enable: boolean) => void;
  readOnly?: boolean;
}) {
  const byGroup = GROUPS.map((group) => ({
    group,
    label: AI_MODULE_GROUP_LABELS[group],
    items: modules.filter((m) => m.group === group),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="max-h-[26rem] space-y-4 overflow-y-auto pr-1">
      {byGroup.map(({ group, label, items }) => {
        const runnable = items.filter((m) => m.hasDetector);
        const enabledInGroup = runnable.filter((m) => !excluded.has(m.code)).length;
        return (
          <div key={group}>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                {label}
              </p>
              {!readOnly && onToggleGroup && runnable.length > 0 && (
                <div className="flex gap-1 text-[10px] font-semibold">
                  <button
                    type="button"
                    onClick={() => onToggleGroup(group, true)}
                    className="rounded px-1.5 py-0.5 text-indigo-600 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-500/10"
                  >
                    Hammasi
                  </button>
                  <span className="text-slate-300 dark:text-slate-600">|</span>
                  <button
                    type="button"
                    onClick={() => onToggleGroup(group, false)}
                    className="rounded px-1.5 py-0.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-white/5"
                  >
                    Hech biri
                  </button>
                </div>
              )}
              <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500">
                {enabledInGroup}/{runnable.length}
              </span>
            </div>
            <div className="space-y-0.5">
              {items.map((m) => {
                const checked = !excluded.has(m.code);
                const disabled = readOnly || !m.hasDetector;
                const globallyOff = !m.active;
                return (
                  <label
                    key={m.code}
                    className={`flex items-start gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors ${
                      disabled
                        ? 'cursor-not-allowed opacity-60'
                        : 'cursor-pointer hover:bg-white/60 dark:hover:bg-white/5'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked && m.hasDetector}
                      disabled={disabled}
                      onChange={() => onToggle(m.code)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-40"
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className={
                          checked && m.hasDetector
                            ? 'text-slate-700 dark:text-slate-300'
                            : 'text-slate-400 dark:text-slate-500'
                        }
                      >
                        #{m.code} {m.name}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                        {globallyOff && (
                          <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                            <Ban size={10} />
                            Global o‘chirilgan
                          </span>
                        )}
                        {!m.hasDetector && (
                          <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-slate-400">
                            <AlertCircle size={10} />
                            Aniqlash yo‘q
                          </span>
                        )}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
