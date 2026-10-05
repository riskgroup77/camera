import { useState } from 'react';
import { ListChecks } from 'lucide-react';
import { cn } from '../../ui';

/** Hodisa bo‘yicha operator ko‘rsatmasi (SOP) — Milestone'dagi "alarm
 *  instructions" kabi. Belgilar faqat shu oynada saqlanadi: maqsad —
 *  operator qadamni unutmasligi, hisobot emas (natija izohga yoziladi).
 *  Hodisa almashganda holat tozalanishi uchun chaqiruvchi `key` beradi. */
export default function EventSopChecklist({ steps }: { steps: string[] }) {
  const [done, setDone] = useState<Set<number>>(() => new Set());
  if (steps.length === 0) return null;

  const toggle = (index: number) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <section aria-label="Ko‘rsatma" className="rounded-card border border-border bg-surface-2/60 p-3.5">
      <h3 className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
        <span className="flex items-center gap-1.5">
          <ListChecks size={13} aria-hidden="true" className="text-primary" />
          Ko‘rsatma
        </span>
        <span className="tabular-nums normal-case tracking-normal">
          {done.size}/{steps.length}
        </span>
      </h3>
      <ol className="space-y-1">
        {steps.map((step, index) => (
          <li key={index}>
            <label className="flex cursor-pointer items-start gap-2 text-sm leading-snug">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                checked={done.has(index)}
                onChange={() => toggle(index)}
              />
              <span className={cn('text-fg', done.has(index) && 'text-muted line-through')}>{step}</span>
            </label>
          </li>
        ))}
      </ol>
    </section>
  );
}
