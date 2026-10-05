import { Wifi, WifiOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { branding } from '../../lib/branding';
import { calendarDateInTashkent } from '../../lib/uzDate';
import { MicroLabel, cn } from '../../ui';

const WEEKDAYS = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'];
const MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];

/** Soat/sana — institut vaqti (Toshkent) bo'yicha: devor ekrani
 *  turgan kompyuterning vaqt mintaqasi noto'g'ri sozlangan bo'lsa ham
 *  ekrandagi kun serverdagi kun bilan bir xil bo'ladi. */
export function tashkentClock(now: Date): { hh: string; mm: string; ss: string; dateLabel: string } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tashkent',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(now);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';
  // Soat yonida kalendar sanasi (tungi 02:14 da ham bugungi sana).
  const iso = calendarDateInTashkent(now);
  const [y, m, d] = iso.split('-').map(Number);
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return {
    hh: pick('hour') === '24' ? '00' : pick('hour'),
    mm: pick('minute'),
    ss: pick('second'),
    dateLabel: `${WEEKDAYS[weekday]}, ${d}-${MONTHS[m - 1]} ${y}`,
  };
}

function tashkentHhmm(value: Date): string {
  const { hh, mm } = tashkentClock(value);
  return `${hh}:${mm}`;
}

/** So'rov xatoga uchramasdan "osilib" qolishi mumkin (tarmoq qora tuynuk,
 *  proksi ushlab qolgan ulanish): bunda `online` true bo'lib qolaveradi.
 *  Ekran kunlab qarovsiz turadi — ertalabki raqamlarni kechqurun ham
 *  "Ulangan" yozuvi bilan ko'rsatish eng yomon xato. So'rov davri 20 s;
 *  uch marta o'tkazib yuborilgan bo'lsa — ma'lumot eskirgan deb hisoblanadi. */
export const STALE_AFTER_MS = 70_000;

export interface ConnectionState {
  /** true — yashil "Ulangan"; false — ogohlantiruvchi holat. */
  ok: boolean;
  /** Zaldan o'qiladigan chiroq: BITTA so'z. */
  label: string;
  /** Ekranga chiqmaydi — ekran o'quvchi va sichqoncha uchun to'liq izoh. */
  title: string;
}

/** Ulanish chirog'idagi so'z va holat. `now` — test uchun beriladi. */
export function connectionState(online: boolean, updatedAt: Date | null, now: Date): ConnectionState {
  const upd = updatedAt ? tashkentHhmm(updatedAt) : '—';
  if (!online) return { ok: false, label: 'Uzildi', title: `Ulanish uzildi · oxirgi ${upd}` };
  if (!updatedAt) return { ok: false, label: 'Kutilmoqda', title: "Ma'lumot hali kelmadi" };
  const ageMs = now.getTime() - updatedAt.getTime();
  if (ageMs > STALE_AFTER_MS) {
    const mins = Math.floor(ageMs / 60_000);
    const ago = mins >= 60 ? `${Math.floor(mins / 60)} soat` : `${Math.max(1, mins)} daqiqa`;
    return { ok: false, label: 'Eskirgan', title: `Yangilanmayapti · ${ago} oldingi ma'lumot (${upd})` };
  }
  return { ok: true, label: 'Ulangan', title: `Ulangan · ${upd}` };
}

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function WallHeader({ online, updatedAt }: { online: boolean; updatedAt: Date | null }) {
  const now = useNow();
  const { hh, mm, ss, dateLabel } = tashkentClock(now);
  const conn = connectionState(online, updatedAt, now);
  return (
    <header className="flex shrink-0 items-stretch gap-[1em] border border-border bg-surface px-[0.9em] py-[0.5em]">
      <img src="/favicon.svg" alt="" className="h-[2.4em] w-[2.4em] shrink-0 self-center" />
      <div className="min-w-0 self-center truncate text-[1.45em] font-semibold leading-tight tracking-tight text-fg">
        {branding.orgName}
      </div>

      <div className="ms-auto flex items-stretch gap-[1.2em]">
        {/* Ulanish chirog'i: rang yolg'iz qolmaydi — bitta so'z ham yoziladi. */}
        <div
          role="status"
          title={conn.title}
          className={cn(
            'flex items-center gap-[0.5em] self-center border px-[0.8em] py-[0.35em]',
            conn.ok ? 'border-success/50 bg-success-soft' : 'wall-blink border-danger/60 bg-danger-soft',
          )}
        >
          {conn.ok ? (
            <Wifi className={cn('h-[1em] w-[1em] text-success')} aria-hidden="true" />
          ) : (
            <WifiOff className={cn('h-[1em] w-[1em] text-danger')} aria-hidden="true" />
          )}
          <span className={cn('intel-micro !text-[0.62em]', conn.ok ? '!text-success' : '!text-danger')}>{conn.label}</span>
        </div>
        <div className="flex flex-col items-end justify-center border-s border-border ps-[1.2em] leading-none">
          {/* Uzoqdan o'qiladigan asosiy raqam — shuning uchun eng katta. */}
          <div className="intel-code text-[3.4em] font-semibold leading-[0.85] tracking-tight text-fg">
            {hh}:{mm}
            <span className="text-[0.42em] text-subtle">:{ss}</span>
          </div>
          <MicroLabel className="mt-[0.5em]">{dateLabel}</MicroLabel>
        </div>
      </div>
    </header>
  );
}
