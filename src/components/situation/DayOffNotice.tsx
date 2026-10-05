import { CalendarOff } from 'lucide-react';
import { useApiResource } from '../../lib/useApiResource';
import { dayInfoPath, type DayInfo } from '../../lib/situationApi';
import { Button, cn, formatUzDate } from '../../ui';

/**
 * Tanlangan kun dam olish yoki bayram bo'lsa — sahifalar hamma joyda "0"
 * ko'rsatib, foydalanuvchini "tizim ishlamayapti" deb o'ylatmasin: sababini
 * ayting va oxirgi ish kuniga bir bosishda o'tkazing.
 */
export default function DayOffNotice({
  date,
  onPick,
  className,
}: {
  date: string;
  onPick: (date: string) => void;
  className?: string;
}) {
  const { data } = useApiResource<DayInfo>(dayInfoPath(date));
  if (!data || data.isWorkDay) return null;
  return (
    <div
      role="status"
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-warning/30 bg-warning-soft px-4 py-3 text-[13px] text-fg',
        className,
      )}
    >
      <CalendarOff size={18} className="shrink-0 text-warning" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <b>{formatUzDate(data.date, { year: false })}</b> — {data.reason}. Davomat bu kunda yozilmaydi, shuning uchun sonlar 0.
      </span>
      {data.lastWorkDay && (
        <Button size="sm" variant="secondary" onClick={() => onPick(data.lastWorkDay!)}>
          Oxirgi ish kunini ko‘rish ({formatUzDate(data.lastWorkDay, { year: false })})
        </Button>
      )}
    </div>
  );
}
