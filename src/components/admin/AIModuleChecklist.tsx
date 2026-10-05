import { useId } from 'react';
import { AlertCircle, Ban } from 'lucide-react';
import { cn, focusRing } from '../../ui';
import { Checkbox } from '../settings/kit';
import { AI_MODULE_GROUP_LABELS } from '../../lib/aiModuleGroups';
import type { AIModuleGroup, CameraModuleOption } from '../../types';

const GROUPS = Object.keys(AI_MODULE_GROUP_LABELS) as AIModuleGroup[];

const linkButton = cn('rounded px-1.5 py-0.5 text-xs font-medium transition-colors', focusRing);

/** Kamera uchun AI modullari ro'yxati (toifalar bo'yicha). `excluded` —
 *  o'chirilgan kodlar; aniqlash logikasi yo'q modullar tanlanmaydi. */
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
  const idPrefix = useId();
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
          <div key={group} role="group" aria-labelledby={`${idPrefix}-${group}`} className="min-w-0">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <p id={`${idPrefix}-${group}`} className="min-w-0 truncate text-[13px] font-semibold uppercase tracking-wide text-muted">
                {group}. {label}
              </p>
              <div className="flex shrink-0 items-center gap-1">
                {!readOnly && onToggleGroup && runnable.length > 0 && (
                  <>
                    {/* Har toifada bir xil «Hammasi / Hech biri» matni takrorlanadi —
                        ekran o'quvchida qaysi toifa ekani bilinmasdi, shuning uchun
                        aria-label'da toifa nomi bor. */}
                    <button
                      type="button"
                      onClick={() => onToggleGroup(group, true)}
                      aria-label={`${group}. ${label} — hamma modullarni yoqish`}
                      className={cn(linkButton, 'text-primary hover:bg-primary-soft')}
                    >
                      Hammasi
                    </button>
                    <span className="text-subtle" aria-hidden="true">
                      |
                    </span>
                    <button
                      type="button"
                      onClick={() => onToggleGroup(group, false)}
                      aria-label={`${group}. ${label} — hamma modullarni o'chirish`}
                      className={cn(linkButton, 'text-muted hover:bg-surface-2 hover:text-fg')}
                    >
                      Hech biri
                    </button>
                  </>
                )}
                {/* "3/5" o'zi hech narsa aytmaydi — nima sanalayotgani izohda. */}
                <span
                  className="ml-1 text-xs font-medium tabular-nums text-muted"
                  title={`Ishlaydigan ${runnable.length} ta moduldan ${enabledInGroup} tasi yoqilgan`}
                >
                  <span aria-hidden="true">
                    {enabledInGroup}/{runnable.length}
                  </span>
                  <span className="sr-only">{`Ishlaydigan ${runnable.length} ta moduldan ${enabledInGroup} tasi yoqilgan`}</span>
                </span>
              </div>
            </div>
            <div className="space-y-0.5">
              {items.map((m) => {
                const checked = !excluded.has(m.code) && m.hasDetector;
                const disabled = readOnly || !m.hasDetector;
                const globallyOff = !m.active;
                const flags =
                  globallyOff || !m.hasDetector ? (
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      {globallyOff && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-warning">
                          <Ban size={11} aria-hidden="true" />
                          Global o‘chirilgan
                        </span>
                      )}
                      {!m.hasDetector && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-muted">
                          <AlertCircle size={11} aria-hidden="true" />
                          Aniqlash yo‘q
                        </span>
                      )}
                    </span>
                  ) : undefined;
                return (
                  <Checkbox
                    key={m.code}
                    checked={checked}
                    disabled={disabled}
                    onChange={() => onToggle(m.code)}
                    label={
                      <span className={cn('font-normal', checked ? 'text-fg' : 'text-muted')}>
                        <span className="font-mono text-xs text-muted">#{m.code}</span> {m.name}
                      </span>
                    }
                    description={flags}
                    className={cn('rounded-control px-2 py-1.5 transition-colors', !disabled && 'hover:bg-surface-2')}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
