import { useCallback, useEffect, useState } from 'react';
import { CalendarPlus, Sparkles, Trash2 } from 'lucide-react';
import { ApiError, isAbortError } from '../../lib/apiClient';
import {
  addHoliday,
  addStandardHolidays,
  deleteHoliday,
  listHolidays,
  type Holiday,
} from '../../lib/attendancePolicyApi';
import { todayInTashkent } from '../../lib/uzDate';
import { Button, CodeText, ErrorState, IconButton, Input, IntelPanel, MicroLabel, Skeleton, formatUzDate, useToast } from '../../ui';

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Bayram va qo'shimcha dam olish kunlari: bu sanalarda hech kim "kelmadi"
 *  yoki "kech keldi" deb yozilmaydi (camera-api/app/routers/attendance_policy.py). */
export default function HolidaysPanel({ token, canEdit }: { token: string | null; canEdit: boolean }) {
  const toast = useToast();
  const [year, setYear] = useState(() => Number(todayInTashkent().slice(0, 4)));
  const [items, setItems] = useState<Holiday[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [date, setDate] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setItems(null);
    listHolidays(token, year, { signal: controller.signal })
      .then((rows) => {
        setItems(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorText(err, "Ro'yxatni olib bo'lmadi"));
      });
    return () => controller.abort();
  }, [token, year, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    try {
      toast.success(await action());
      reload();
    } catch (err) {
      toast.error(errorText(err, "Saqlab bo'lmadi"));
    } finally {
      setBusy(false);
    }
  }

  const recomputedNote = (n: number) => (n ? ` · ${n} ta davomat yozuvi tuzatildi` : '');

  return (
    <IntelPanel
      title="Bayram va dam olish kunlari"
      right={
        <span className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => setYear((y) => y - 1)} aria-label="Oldingi yil">
            ‹
          </Button>
          <CodeText className="text-[13px] font-semibold">{year}</CodeText>
          <Button size="sm" variant="ghost" onClick={() => setYear((y) => y + 1)} aria-label="Keyingi yil">
            ›
          </Button>
        </span>
      }
      bodyClassName="flex flex-col gap-3 p-3"
    >
      <p className="text-[12px] text-muted">
        Bu sanalarda hech kim «kelmadi» yoki «kech keldi» deb yozilmaydi. O‘tgan sanani belgilasangiz, o‘sha kungi
        yozuvlar ham tuzatiladi. Ramazon va Qurbon hayit sanasini har yili qo‘lda qo‘shing.
      </p>

      {canEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            Sana
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9 w-auto" />
          </label>
          <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[12px] text-muted">
            Nomi
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Masalan: Ramazon hayiti" maxLength={120} className="h-9" />
          </label>
          <Button
            icon={CalendarPlus}
            disabled={busy || !date || !name.trim()}
            onClick={() =>
              run(async () => {
                const res = await addHoliday(token, { date, name: name.trim() });
                setDate('');
                setName('');
                if (Number(res.date.slice(0, 4)) !== year) setYear(Number(res.date.slice(0, 4)));
                return `«${res.name}» qo‘shildi${recomputedNote(res.recomputed ?? 0)}`;
              })
            }
          >
            Qo‘shish
          </Button>
          <Button
            variant="ghost"
            icon={Sparkles}
            disabled={busy}
            title="1-yanvar, 8-mart, 21-mart, 9-may, 1-sentabr, 1-oktabr, 8-dekabr"
            onClick={() =>
              run(async () => {
                const res = await addStandardHolidays(token, year);
                return res.added
                  ? `${year}-yil bayramlari: ${res.added} ta qo‘shildi${recomputedNote(res.recomputed)}`
                  : 'Bu yilning bayramlari allaqachon bor';
              })
            }
          >
            {year}-yil bayramlari
          </Button>
        </div>
      )}

      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : items === null ? (
        <Skeleton className="h-20" />
      ) : items.length === 0 ? (
        <p className="text-[13px] text-muted">{year}-yil uchun dam olish kuni kiritilmagan.</p>
      ) : (
        <ul className="divide-y divide-border border border-border">
          {items.map((item) => (
            <li key={item.date} className="flex items-center gap-3 px-3 py-1.5">
              <CodeText className="w-24 shrink-0 text-[12px] text-fg">{formatUzDate(item.date)}</CodeText>
              <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{item.name}</span>
              {item.date === todayInTashkent() && <MicroLabel className="!text-success">bugun</MicroLabel>}
              {canEdit && (
                <IconButton
                  icon={Trash2}
                  size="sm"
                  variant="danger"
                  label={`${item.name} — olib tashlash`}
                  disabled={busy}
                  onClick={() => run(async () => {
                    await deleteHoliday(token, item.date);
                    return `«${item.name}» olib tashlandi`;
                  })}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </IntelPanel>
  );
}
