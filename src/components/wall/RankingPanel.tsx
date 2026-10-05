import { Timer, Trophy } from 'lucide-react';
import type { WallUnit } from '../../lib/wallApi';
import { MicroLabel, cn } from '../../ui';
import { RAG_LETTER, RAG_LABEL, RAG_SOLID, RAG_TEXT, RATE_RAG, rag } from '../../ui/rag';
import { WallPanel } from './primitives';

function UnitBar({ unit, rank }: { unit: WallUnit; rank: number | null }) {
  // Hukm butun tizimdagi yagona svetofor qoidasidan.
  const tone = rag(unit.rate, RATE_RAG);
  const pct = unit.rate ?? 0;
  return (
    <li className="flex min-w-0 shrink-0 items-center gap-[0.6em]">
      {/* Svetofor ustuni — qatorning chap qirrasi. */}
      <span aria-hidden="true" className={cn('h-[1.6em] w-[0.28em] shrink-0', RAG_SOLID[tone])} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-[0.5em] text-[0.85em]">
          <span className="intel-code w-[1.4em] shrink-0 text-subtle">{rank ?? '·'}</span>
          <span className="min-w-0 flex-1 truncate text-fg">{unit.name}</span>
          <span className="intel-code shrink-0 text-[0.85em] text-subtle">
            {unit.present}/{unit.total}
          </span>
          <span className={cn('intel-code w-[3.2em] shrink-0 text-right font-semibold', RAG_TEXT[tone])}>
            {unit.rate === null ? '—' : `${Math.round(unit.rate)}%`}
          </span>
          <span className={cn('intel-code w-[1em] shrink-0 text-right text-[0.8em] font-bold', RAG_TEXT[tone])} title={RAG_LABEL[tone]}>
            {RAG_LETTER[tone]}
          </span>
        </span>
        <span aria-hidden="true" className="mt-[0.2em] block h-[0.25em] w-full bg-surface-3">
          <span
            className={cn('block h-full transition-[width] duration-1000 ease-out', RAG_SOLID[tone])}
            style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          />
        </span>
      </span>
    </li>
  );
}

function Group({ title, units, startRank }: { title: string; units: WallUnit[]; startRank?: (i: number) => number }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="mb-[0.4em] shrink-0 border-b border-border pb-[0.25em]">
        <MicroLabel className="!text-[0.6em]">{title}</MicroLabel>
      </div>
      {units.length === 0 ? (
        <div className="text-[0.78em] text-muted">Ma'lumot yo'q</div>
      ) : (
        <ul className="flex min-h-0 flex-1 flex-col justify-evenly gap-[0.2em] overflow-hidden">
          {units.map((u, i) => (
            <UnitBar key={u.id} unit={u} rank={startRank ? startRank(i) : null} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function RankingPanel({
  top,
  bottom,
  chronic,
  chronicError,
}: {
  top: WallUnit[];
  bottom: WallUnit[];
  chronic: number | null;
  /** So'rov xato bergan bo'lsa — "—" ning sababi ekranda yoziladi. */
  chronicError?: boolean;
}) {
  // Kichik institutda top va bottom kesishishi mumkin — pastkilarni takrorlamaymiz.
  const topIds = new Set(top.map((u) => u.id));
  const bottomOnly = bottom.filter((u) => !topIds.has(u.id));
  return (
    <WallPanel area="D" title="Bo'linmalar reytingi" icon={<Trophy />}>
      <div className="flex min-h-0 flex-1 flex-col gap-[0.6em]">
        {/* "5" qattiq yozilgan edi: bo'linmalar kam bo'lsa ekranda
            3 ta qator turib, sarlavhada 5 deb yozilardi. */}
        <Group title={`Eng yaxshi ${top.length}`} units={top} startRank={(i) => i + 1} />
        {/* Bu ro'yxat — eng pastdagilar; "1, 2, 3" raqamlari uni yaxshi
            o'rin kabi ko'rsatardi, shuning uchun raqamlanmaydi. */}
        {bottomOnly.length > 0 && <Group title="Eng past" units={bottomOnly} />}
        <div className="flex shrink-0 items-center gap-[0.8em] border border-warning/50 bg-warning-soft px-[0.9em] py-[0.6em]">
          <Timer className="h-[1.6em] w-[1.6em] shrink-0 text-warning" />
          <div className="min-w-0 flex-1 leading-tight">
            {/* Ko'rsatkich kelmaganlarni ham sanaydi — sarlavha faqat
                kechikish haqida edi va raqamni kam ko'rsatardi. */}
            <MicroLabel
              className="intel-micro-wrap block !text-[0.62em] !text-fg"
              title="So'nggi 14 kunda uch va undan ko'p marta kech qolgan yoki kelmagan xodimlar"
            >
              Takror kechikkan
            </MicroLabel>
            {chronic === null && (
              <div className="mt-[0.25em] text-[0.68em] text-muted">{chronicError ? 'olinmadi' : 'yuklanmoqda…'}</div>
            )}
          </div>
          <div className="intel-code text-[2.4em] font-semibold leading-none text-warning">
            {chronic ?? <span className="text-muted" title="Hisob mavjud emas">—</span>}
          </div>
        </div>
      </div>
    </WallPanel>
  );
}
