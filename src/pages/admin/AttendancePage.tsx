import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, LogOut, Loader2, LogIn, Trash2, UserCheck, UserX, Clock3, TrendingUp, CalendarDays } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import StatCard from '../../components/StatCard';
import Modal from '../../components/Modal';
import Badge from '../../components/Badge';
import ConfirmDialog from '../../components/ConfirmDialog';
import { api, fetchAllPages } from '../../lib/apiClient';
import { useAuth } from '../../lib/auth';
import { toLocalDateString } from '../../lib/date';
import type { AttendanceDay, AttendanceDayStatus, StudentStaffRecord } from '../../types';

const MONTH_NAMES = [
  'Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
  'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr',
];
const WEEKDAY_LABELS = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'];

type CellStatus = AttendanceDayStatus | 'malumotYoq';

interface CalendarCell {
  date: string;
  status: CellStatus;
  checkIn?: string;
  checkOut?: string;
  earlyLeave?: boolean;
  isRecord: boolean;
}

const STATUS_STYLE: Record<CellStatus, string> = {
  keldi: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400',
  kech_keldi: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
  kelmadi: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400',
  dam_olish: 'bg-slate-100 text-slate-400 dark:bg-white/5 dark:text-slate-500',
  malumotYoq: 'bg-slate-50 text-slate-300 dark:bg-white/[0.03] dark:text-slate-600',
};

const STATUS_LABEL: Record<CellStatus, string> = {
  keldi: 'Keldi',
  kech_keldi: 'Kech keldi',
  kelmadi: 'Kelmadi',
  dam_olish: 'Dam olish',
  malumotYoq: "Ma'lumot yo'q",
};

const STATUS_BADGE_TONE: Record<CellStatus, 'green' | 'amber' | 'red' | 'slate'> = {
  keldi: 'green',
  kech_keldi: 'amber',
  kelmadi: 'red',
  dam_olish: 'slate',
  malumotYoq: 'slate',
};

const WEEKDAY_FULL_NAMES = [
  'Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba',
];

function formatFullDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return `${d}-${MONTH_NAMES[m - 1]} ${y}, ${WEEKDAY_FULL_NAMES[date.getDay()]}`;
}

function mondayIndex(date: Date) {
  return (date.getDay() + 6) % 7;
}

/** Backenddan kelgan (kamdan-kam) yozuvlarni to'liq oy setkasiga to'ldiradi —
 * hafta oxiri/kelajak kunlar "Dam olish", yozuv topilmagan o'tgan ish kuni
 * esa haqiqatan ham "Ma'lumot yo'q" deb ko'rsatiladi (hali AI davomat moduli
 * ishlamayapti, shuning uchun bo'sh kunni soxta "Kelmadi" deb belgilamaymiz). */
function buildMonthGrid(records: AttendanceDay[], year: number, month: number): CalendarCell[] {
  const byDate = new Map(records.map((r) => [r.date, r]));
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const cells: CalendarCell[] = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d);
    const iso = toLocalDateString(date);
    const dow = date.getDay();
    const record = byDate.get(iso);

    if (record) {
      cells.push({
        date: iso,
        status: record.status,
        checkIn: record.checkIn,
        checkOut: record.checkOut,
        earlyLeave: record.earlyLeave,
        isRecord: true,
      });
    } else if (date > today || dow === 0 || dow === 6) {
      cells.push({ date: iso, status: 'dam_olish', isRecord: false });
    } else {
      cells.push({ date: iso, status: 'malumotYoq', isRecord: false });
    }
  }
  return cells;
}

export default function AttendancePage() {
  const { token } = useAuth();
  const [people, setPeople] = useState<StudentStaffRecord[]>([]);
  const [personId, setPersonId] = useState('');
  const now = new Date();
  const [viewYear, setViewYear] = useState(now.getFullYear());
  const [viewMonth, setViewMonth] = useState(now.getMonth());
  const [records, setRecords] = useState<AttendanceDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<AttendanceDay | null>(null);
  const [selectedDay, setSelectedDay] = useState<CalendarCell | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!token) return;
    fetchAllPages<StudentStaffRecord>('/api/students-staff', token)
      .then((items) => {
        setPeople(items);
        setPersonId((cur) => cur || items[0]?.id || '');
      })
      .catch(() => {
        /* ulanish muvaffaqiyatsiz — bo'sh ro'yxat bilan davom etamiz */
      });
  }, [token]);

  useEffect(() => {
    if (!token || !personId) return;
    let cancelled = false;
    setLoading(true);
    const month = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}`;
    api
      .get<AttendanceDay[]>(`/api/attendance/${personId}?month=${month}`, token)
      .then((res) => {
        if (!cancelled) {
          setRecords(res);
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
  }, [token, personId, viewYear, viewMonth, reloadKey]);

  async function handleDelete() {
    if (!deleting || !personId) return;
    await api.del(`/api/attendance/${personId}/${deleting.date}`, token);
    setDeleting(null);
    setSelectedDay((cur) => (cur && cur.date === deleting.date ? null : cur));
    setReloadKey((k) => k + 1);
  }

  const person = people.find((p) => p.id === personId);
  const days = useMemo(() => buildMonthGrid(records, viewYear, viewMonth), [records, viewYear, viewMonth]);
  const leadingBlanks = mondayIndex(new Date(viewYear, viewMonth, 1));

  const stats = useMemo(() => {
    const workDays = days.filter((d) => d.status !== 'dam_olish' && d.status !== 'malumotYoq');
    const present = workDays.filter((d) => d.status === 'keldi').length;
    const late = workDays.filter((d) => d.status === 'kech_keldi').length;
    const absent = workDays.filter((d) => d.status === 'kelmadi').length;
    const earlyLeave = workDays.filter((d) => d.earlyLeave).length;
    const rate = workDays.length ? Math.round(((present + late) / workDays.length) * 100) : 0;
    return { present, late, absent, earlyLeave, rate };
  }, [days]);

  function shiftMonth(delta: number) {
    let m = viewMonth + delta;
    let y = viewYear;
    if (m < 0) {
      m = 11;
      y -= 1;
    } else if (m > 11) {
      m = 0;
      y += 1;
    }
    setViewMonth(m);
    setViewYear(y);
  }

  return (
    <section className="glass p-6">
      <PageHeader
        title="Davomat kalendari"
        subtitle="Xodim/talaba bo'yicha kalendar ko'rinishida davomat tarixi"
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <select
          value={personId}
          onChange={(e) => setPersonId(e.target.value)}
          className="rounded-xl border border-white/80 bg-white/60 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        >
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.fullName} — {p.groupOrPosition}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => shiftMonth(-1)}
            className="glass-deep rounded-xl p-2 text-slate-500 transition-colors hover:text-indigo-500 dark:text-slate-400"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="w-36 text-center text-sm font-bold text-slate-900 dark:text-slate-100">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </span>
          <button
            onClick={() => shiftMonth(1)}
            className="glass-deep rounded-xl p-2 text-slate-500 transition-colors hover:text-indigo-500 dark:text-slate-400"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard icon={<UserCheck size={20} />} value={stats.present} label="Keldi" tone="green" />
        <StatCard icon={<Clock3 size={20} />} value={stats.late} label="Kech keldi" tone="amber" />
        <StatCard icon={<UserX size={20} />} value={stats.absent} label="Kelmadi" tone="red" />
        <StatCard icon={<LogOut size={20} />} value={stats.earlyLeave} label="Erta ketdi" tone="amber" />
        <StatCard icon={<TrendingUp size={20} />} value={`${stats.rate}%`} label="Davomat" tone="indigo" />
      </div>

      {loading && !person ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <div className="glass-deep p-4">
          <div className="mb-2 grid grid-cols-7 gap-2 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            {WEEKDAY_LABELS.map((w) => (
              <span key={w}>{w}</span>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-2">
            {Array.from({ length: leadingBlanks }).map((_, i) => (
              <div key={`blank-${i}`} />
            ))}
            {days.map((day) => {
              const dayNum = Number(day.date.slice(-2));
              const clickable = day.status !== 'dam_olish';
              return (
                <div
                  key={day.date}
                  onClick={clickable ? () => setSelectedDay(day) : undefined}
                  title={`${STATUS_LABEL[day.status]}${day.checkIn ? ` · ${day.checkIn}` : ''}${day.earlyLeave ? ' · Erta ketdi' : ''}`}
                  className={`group relative flex aspect-square flex-col items-center justify-center rounded-lg text-xs font-semibold ${STATUS_STYLE[day.status]} ${clickable ? 'cursor-pointer transition-transform hover:scale-[1.04]' : ''}`}
                >
                  {day.earlyLeave && (
                    <span className="absolute -left-1 -top-1 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white dark:ring-slate-900" />
                  )}
                  <span>{dayNum}</span>
                  {day.checkIn && <span className="text-[9px] font-normal opacity-80">{day.checkIn}</span>}
                  {day.isRecord && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleting({ date: day.date, status: day.status as AttendanceDayStatus, checkIn: day.checkIn });
                      }}
                      title="Yozuvni o'chirish"
                      className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-white text-slate-500 opacity-0 shadow-sm ring-1 ring-slate-200 transition-opacity hover:!opacity-100 hover:text-red-600 group-hover:opacity-100 dark:bg-slate-800 dark:text-slate-400 dark:ring-white/10 dark:hover:text-red-400"
                    >
                      <Trash2 size={9} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap gap-3 border-t border-white/70 pt-3 text-xs text-slate-500 dark:border-white/10 dark:text-slate-400">
            {(Object.keys(STATUS_LABEL) as CellStatus[]).map((s) => (
              <span key={s} className="flex items-center gap-1.5">
                <span className={`h-2.5 w-2.5 rounded-sm ${STATUS_STYLE[s].split(' ')[0]}`} />
                {STATUS_LABEL[s]}
              </span>
            ))}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Davomat yozuvini o'chirish"
        message={deleting ? `${person?.fullName ?? ''} uchun ${deleting.date} sanasidagi davomat yozuvini o'chirishni tasdiqlaysizmi?` : ''}
        onCancel={() => setDeleting(null)}
        onConfirm={handleDelete}
      />

      <Modal open={!!selectedDay} onClose={() => setSelectedDay(null)} title={person?.fullName} maxWidth="max-w-sm">
        {selectedDay && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <CalendarDays size={15} />
              {formatFullDate(selectedDay.date)}
            </div>

            <div>
              <Badge tone={STATUS_BADGE_TONE[selectedDay.status]}>{STATUS_LABEL[selectedDay.status]}</Badge>
            </div>

            {selectedDay.isRecord ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-white/60 p-3 dark:bg-white/5">
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <LogIn size={12} />
                    Keldi
                  </div>
                  <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
                    {selectedDay.checkIn ?? '—'}
                  </p>
                </div>
                <div className="rounded-xl bg-white/60 p-3 dark:bg-white/5">
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <LogOut size={12} />
                    Ketdi
                  </div>
                  <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
                    {selectedDay.checkOut ?? '—'}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-400 dark:text-slate-500">
                Bu kun uchun kamera orqali qayd etilgan davomat yozuvi yo'q.
              </p>
            )}

            {selectedDay.earlyLeave && (
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-600 dark:text-amber-400">
                <LogOut size={13} />
                Erta ketgan — belgilangan ish vaqtidan oldin chiqib ketgan
              </p>
            )}

            {selectedDay.isRecord && (
              <button
                onClick={() => {
                  setDeleting({
                    date: selectedDay.date,
                    status: selectedDay.status as AttendanceDayStatus,
                    checkIn: selectedDay.checkIn,
                  });
                  setSelectedDay(null);
                }}
                className="glass-btn-danger flex items-center justify-center gap-1.5 self-start !py-2"
              >
                <Trash2 size={13} />
                Yozuvni o'chirish
              </button>
            )}
          </div>
        )}
      </Modal>
    </section>
  );
}
