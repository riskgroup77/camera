import { useMemo } from 'react';
import { cn } from '../../ui';
import { isOpenStatus, slaInfo } from '../../lib/eventWorkflow';
import { useSharedNow } from '../../lib/sharedClock';
import type { AIEvent } from '../../types';

/** Svetofor: muddat ichida — yashil, yaqinlashdi — sariq, o'tdi — qizil.
 *  Rang yolg'iz qolmaydi: yonida doim qolgan vaqt yozilgan. */
const LAMP: Record<'ok' | 'soon' | 'overdue', { dot: string; text: string; word: string }> = {
  ok: { dot: 'bg-success', text: 'text-success', word: 'Muddat ichida' },
  soon: { dot: 'bg-warning', text: 'text-warning', word: 'Muddat yaqin' },
  overdue: { dot: 'bg-danger', text: 'text-danger', word: "Muddati o'tgan" },
};

/** Hal qilish muddati (SLA): qolgan vaqt monoshriftda + holat chirog'i.
 *  Qaror qilingan hodisada hech narsa ko'rsatilmaydi. */
export default function SlaBadge({ event, className = '' }: { event: Pick<AIEvent, 'status' | 'dueAt'>; className?: string }) {
  const active = !!event.dueAt && isOpenStatus(event.status);
  // Umumiy soat: ro'yxatdagi har bir yorliq o'z taymerini ochmaydi.
  const nowMs = useSharedNow(active);
  const now = useMemo(() => new Date(nowMs), [nowMs]);
  const info = slaInfo(event, now);
  if (info.state === 'none') return null;
  const lamp = LAMP[info.state];
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', className)}
      title={`${lamp.word}${event.dueAt ? ` · Hal qilish muddati: ${event.dueAt.slice(0, 16).replace('T', ' ')}` : ''}`}
    >
      <span
        aria-hidden="true"
        className={cn('h-1.5 w-1.5 shrink-0 rounded-full', lamp.dot, info.state === 'overdue' && 'intel-pulse')}
      />
      <span className={cn('intel-code text-[12px] font-semibold', lamp.text)}>{info.label}</span>
    </span>
  );
}
