import { MicroLabel, cn, focusRing } from '../../ui';
import type { HisobotCriterion } from '../../lib/hisobotApi';

/**
 * Ko'rsatkich tanlash — yon panel emas, yuqoridagi gorizontal lenta.
 *
 * Rahbar avval "nimani o'lchayapmiz" ni bitta qatorda ko'radi, keyin
 * pastda javobni. Hisoblab bo'lmaydigan ko'rsatkich o'chirilgan holda
 * turadi va SABABINI aytadi — jimgina yo'qolib qolmaydi.
 */
export default function CriteriaStrip({
  criteria,
  value,
  onChange,
  loading,
}: {
  criteria: HisobotCriterion[] | null;
  value: string;
  onChange: (key: string) => void;
  loading: boolean;
}) {
  if (!criteria) {
    return (
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <MicroLabel>Ko&apos;rsatkich</MicroLabel>
        <span className="h-5 w-64 animate-pulse bg-surface-3" aria-hidden="true" />
      </div>
    );
  }

  const active = criteria.find((c) => c.key === value) ?? criteria.find((c) => c.available) ?? null;

  return (
    <div className="border-b border-border">
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1 px-3 py-2">
        <MicroLabel className="me-2">Ko&apos;rsatkich</MicroLabel>
        {criteria.map((item) => {
          const selected = item.key === active?.key;
          return (
            <button
              key={item.key}
              type="button"
              disabled={!item.available || loading}
              onClick={() => onChange(item.key)}
              title={item.available ? item.description : item.unavailable ?? undefined}
              aria-pressed={selected}
              className={cn(
                'intel-code border px-2 py-1 text-[11px] uppercase tracking-[0.06em] transition-colors',
                focusRing,
                selected
                  ? 'border-primary bg-primary text-primary-fg'
                  : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg',
                !item.available && 'cursor-not-allowed opacity-45 hover:border-border hover:text-muted',
              )}
            >
              {item.code ? <span className="me-1 opacity-70">#{item.code}</span> : null}
              {item.label}
            </button>
          );
        })}
      </div>
      {/* Tanlangan ko'rsatkich nimani o'lchashi — doim ko'rinib turadi:
          "kech keldi" nimaga nisbatan hisoblanganini bilmasdan raqamga
          ishonib bo'lmaydi. */}
      {active && (
        <p className="border-t border-border bg-surface-2 px-3 py-1.5 text-[11px] leading-snug text-muted">
          {active.available ? active.description : active.unavailable}
        </p>
      )}
      {/* Xira tugmalar sababi — o'chirilgan tugma ustida brauzer izohni ko'pincha ko'rsatmaydi. */}
      {criteria.some((c) => !c.available) && (
        <details className="border-t border-border px-3 py-1.5 text-[11px] text-muted">
          <summary className="cursor-pointer select-none">
            Nega ba&apos;zi ko&apos;rsatkichlar xira? ({criteria.filter((c) => !c.available).length} ta hozir o&apos;lchanmayapti)
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 ps-4">
            {criteria
              .filter((c) => !c.available)
              .map((c) => (
                <li key={c.key}>
                  <b className="text-fg">{c.label}</b> — {c.unavailable ?? 'bu ko‘rsatkich uchun ma’lumot yo‘q'}
                </li>
              ))}
          </ul>
        </details>
      )}
    </div>
  );
}
