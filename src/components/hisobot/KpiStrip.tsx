import { CodeText, MicroLabel, cn } from '../../ui';
import { RAG_LABEL, RAG_SOLID, RAG_TEXT, RATE_RAG, rag, type RagThresholds } from '../../ui/rag';
import type { HisobotTile } from '../../lib/hisobotApi';

/**
 * Yuqoridagi asosiy ko'rsatkichlar qatori.
 *
 * Har blok: yorliq, katta raqam, birlik va — agar ko'rsatkich foiz
 * bo'lsa — svetofor hukmi so'z bilan. Rang yolg'iz qolmaydi.
 */

/** Serverning ohangi bilan svetoforni chalkashtirmaymiz: hukmni FAQAT
 *  foizli ko'rsatkichga, o'zimizning yagona qoida bo'yicha qo'yamiz. */
function tileRag(tile: HisobotTile, thresholds: RagThresholds) {
  if (tile.unit !== '%') return 'yoq' as const;
  const numeric = typeof tile.value === 'number' ? tile.value : Number(String(tile.value).replace(',', '.'));
  return rag(Number.isFinite(numeric) ? numeric : null, thresholds);
}

export default function KpiStrip({
  tiles,
  thresholds = RATE_RAG,
}: {
  tiles: HisobotTile[];
  thresholds?: RagThresholds;
}) {
  if (tiles.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
      {tiles.map((tile) => {
        const tone = tileRag(tile, thresholds);
        return (
          <li key={tile.label} className="flex flex-col gap-1.5 bg-surface px-3 py-2.5">
            <span className="flex items-center gap-2">
              {tone !== 'yoq' && (
                <span aria-hidden="true" className={cn('h-2 w-2 shrink-0 rounded-[1px]', RAG_SOLID[tone])} />
              )}
              <MicroLabel className="truncate">{tile.label}</MicroLabel>
            </span>
            <span className="flex items-baseline gap-1">
              <CodeText className={cn('text-[24px] font-semibold leading-none', tone === 'yoq' ? 'text-fg' : RAG_TEXT[tone])}>
                {typeof tile.value === 'number' ? tile.value.toLocaleString('ru-RU') : tile.value}
              </CodeText>
              {tile.unit && <MicroLabel>{tile.unit}</MicroLabel>}
            </span>
            {/* Hukm — bitta so'z. Izoh jumlalari olib tashlandi: yuqoridagi
                ma'lumot satri odamlar sonini allaqachon aytadi. */}
            {tone !== 'yoq' && (
              <span className={cn('intel-code text-[11px]', RAG_TEXT[tone])}>{RAG_LABEL[tone]}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
