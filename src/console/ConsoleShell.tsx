import { useCallback, useEffect, useState, useRef } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { LayoutGroup, motion } from 'motion/react';
import { ChartColumn, Search } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { usePermissions } from '../lib/permissions';
import { homeForRole, isPathAllowedForRole } from '../layouts/shell/navConfig';
import { ConsoleUserMenu } from './ConsoleNav';
import { cn } from '../ui';
import { useLiveAttendance, useLiveEvents } from '../lib/realtime';
import { signalAlarm } from '../lib/alarmSignal';
import { useCommandPaletteHotkey } from '../layouts/shell/useCommandPaletteHotkey';
import CamerasPanel from './panels/CamerasPanel';
import GroupTablePanel from './panels/GroupTablePanel';
import GroupStatsPanel from './panels/GroupStatsPanel';
import ConsolePalette, { type PaletteTarget } from './ConsolePalette';
import { useConsoleFilter } from './consoleFilter';
import { useNazoratSelection } from './nazoratSelection';
import { useGroupLive } from './useGroupLive';
import { useGroupCriteria } from './useGroupCriteria';
import { EASE } from './motion';
import DayOffNotice from '../components/situation/DayOffNotice';

const PULSE_THROTTLE_MS = 10_000;

/**
 * NAZORAT — institutning jonli kamera oynasi.
 *
 * Tartib (2026-09-26, foydalanuvchi talabi): chapda guruh/talabalar jadvali
 * (filtr, holat, hozirgi dars, yuzi bazadami), o'ngda 4 ta aylanuvchi
 * kamera (har 10 s) va tanlangan guruh / institut bo'yicha jonli sanoqlar.
 * Har son bosiladi — kimligi ko'rinadi. Boshqa panellar olib tashlandi.
 *
 * Bitta ekran, siljishsiz: yon menyu yo'q, sahifadan sahifaga
 * o'tilmaydi. Joy yetmasa panel KATTALASHADI (Panel.tsx), ya'ni
 * kontekst yo'qolmaydi. Hisobotlar — ataylab alohida sahifa: u
 * hujjat, konsol esa jonli holat.
 *
 * Filtr (sana va kim) URL'da — ko'rinishni havola qilib yuborish
 * mumkin, lekin marshrut o'zgarmagani uchun konsol qayta yuklanmaydi.
 */

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: number | undefined;
    const tick = () => setNow(new Date());
    const start = () => {
      tick();
      timer = window.setInterval(tick, 1000);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    // Ko'rinmayotgan oynada soat yurmaydi — bekorga ishlamasin.
    const onVisibility = () => (document.hidden ? stop() : start());
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);
  return now;
}

const timeFormat = new Intl.DateTimeFormat('uz-UZ', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'Asia/Tashkent',
});

export default function ConsoleShell() {
  const { role } = useAuth();
  // Cheklangan rol (masalan kamera mas'uli) konsolni ko'rmaydi — o'z sahifasiga.
  if (!isPathAllowedForRole(role, '/')) return <Navigate to={homeForRole(role)} replace />;
  return <Console />;
}

function Console() {
  const { role } = useAuth();
  const { can } = usePermissions();
  // Har panel o'z huquqi bilan: ko'rish huquqi yo'q panel umuman chizilmaydi
  // (avval "Ma'lumot olinmadi" deb chiqardi — xato emas, huquq yo'q edi).
  const canLive = can('viewLive', role);
  const canAttendance = can('manageAttendance', role);
  const canReports = can('viewReports', role);
  const filter = useConsoleFilter();
  const { date, isToday } = filter;
  const selection = useNazoratSelection();
  const now = useClock();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const [pulse, setPulse] = useState(0);
  // Jonli xabarlar to'lqin bo'lib keladi (ertalab ~2/s): har biri 8-10 ta
  // og'ir so'rov yuborardi. Endi 10 soniyada ko'pi bilan bir marta.
  const pulseTimer = useRef<number | null>(null);
  const bumpPulse = useCallback(() => {
    if (pulseTimer.current !== null) return;
    pulseTimer.current = window.setTimeout(() => {
      pulseTimer.current = null;
      setPulse((n) => n + 1);
    }, PULSE_THROTTLE_MS);
  }, []);
  useEffect(() => () => {
    if (pulseTimer.current !== null) window.clearTimeout(pulseTimer.current);
  }, []);
  const canPeople = canAttendance || canReports;
  // Guruh ma'lumoti faqat talabalar uchun (xodimlarda `group` — kafedra id si).
  const groupLive = useGroupLive(canPeople && selection.who === 'talaba' ? selection.group : '', date, isToday, pulse);
  // Guruh kriteriyalari — Nazorat ruxsati bilan (hisobotlar parolisiz).
  const groupCriteria = useGroupCriteria(selection.who === 'talaba' ? selection.group : '', date, pulse, canPeople);

  // Jonli xabar kelganda raqamlar yangilanadi. Ulanish HOLATI hodisalar
  // kanalidan olinadi — davomat kanali holat qaytarmaydi. O'tgan kunni
  // ko'rayotganda jonli yangilanish kerak emas — u kun o'zgarmaydi.
  useLiveAttendance(() => isToday && bumpPulse(), true);
  const canReview = can('reviewEvents', role);
  // Ekran o'quvchi uchun: yangi signal ovoz bilan birga matn sifatida ham e'lon qilinadi.
  const [announcement, setAnnouncement] = useState('');
  const live =
    useLiveEvents((event) => {
      if (canReview && signalAlarm(event)) {
        setAnnouncement(`Yangi signal: ${event.moduleName}, ${event.cameraName}`);
      }
      if (isToday) bumpPulse();
    }, true) === 'live' && isToday;

  // Ctrl/⌘+K — konsol palitrasi: bo'linma, shaxs, kamera va boshqaruv
  // bo'limlari. Tanlov MANZILNI emas, panelni ochadi.
  const togglePalette = useCallback(() => setPaletteOpen((open) => !open), []);
  useCommandPaletteHotkey(togglePalette);

  // Palitra tanlovi: aniq kamera kattalashadi, aniq bo'linma ichi ochiladi,
  // shaxs — o'z sahifasi. `nonce` bir xil obyektni qayta tanlashni ham ushlaydi.
  const navigate = useNavigate();
  const [target, setTarget] = useState<{ panel: string; id: string; nonce: number } | null>(null);
  const openTarget = useCallback(
    (picked: PaletteTarget) => {
      if (picked.panel === 'person') {
        navigate(`/shaxs/${encodeURIComponent(picked.id)}`);
        return;
      }
      setExpanded(picked.panel);
      setTarget(picked.id ? { panel: picked.panel, id: picked.id, nonce: Date.now() } : null);
    },
    [navigate],
  );

  // Esc — yoyilgan panelni yopadi.
  useEffect(() => {
    if (!expanded) return;
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setExpanded(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [expanded]);


  return (
    <LayoutGroup>
    <div className="console-root flex flex-col text-fg">
      {/* Nazorat satri — kamera maydonining yagona boshqaruvi. */}
      <motion.header
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: EASE }}
        className="relative z-20 mx-3 mt-3 flex shrink-0 items-center gap-3 rounded-card border border-white/90 bg-white/72 px-4 py-3 shadow-card backdrop-blur-xl"
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-[#7265ee] text-[11px] font-extrabold text-primary-fg shadow-[0_10px_20px_-12px_rgb(45_83_222/0.9)]">
            FI
          </span>
          <span className="hidden min-w-0 flex-col sm:flex"><b className="truncate text-[13px] tracking-[-0.02em] text-fg">Nazorat</b><small className="truncate text-[10px] font-medium text-muted">Jonli kamera kuzatuvi</small></span>
        </span>

        {/* Qidiruv — palitrani ochadi (Ctrl/⌘+K): bo'linma, shaxs,
            kamera va boshqaruv bo'limlari bitta joydan. Tanlov panelni
            ochadi, sahifaga o'tmaydi. */}
        <button
          type="button"
          onClick={togglePalette}
          className="ms-2 flex h-10 min-w-0 flex-1 items-center gap-2 rounded-control bg-surface-2 px-3 text-left transition-colors hover:bg-primary-soft sm:max-w-md"
        >
          <Search size={15} aria-hidden="true" className="shrink-0 text-subtle" />
          <span className="min-w-0 flex-1 truncate text-[13px] text-subtle">{canAttendance ? "Shaxs, bo‘linma yoki kamera" : "Kamera qidirish"}</span>
          <kbd className="hidden shrink-0 rounded-md bg-white px-1.5 py-0.5 text-[10px] font-semibold text-muted shadow-sm sm:inline">Ctrl K</kbd>
        </button>

        <span className="ms-auto flex items-center gap-3">
          <span className="hidden text-[13px] font-bold tabular-nums text-fg sm:block">{timeFormat.format(now)}</span>
          <span className={cn('flex items-center gap-1.5', live ? 'text-success' : 'text-subtle')}>
            <span className={cn('h-1.5 w-1.5 rounded-full bg-current', live && 'live-dot')} aria-hidden="true" />
            <span className="text-[11px] font-semibold !text-current">{live ? 'Jonli' : isToday ? 'Aloqa yo‘q' : 'Arxiv'}</span>
          </span>
          {canReports && (
            <Link
              to="/hisobotlar"
              className="flex h-10 items-center gap-1.5 rounded-control bg-primary-soft px-3 text-[13px] font-semibold text-primary transition-colors hover:bg-primary/15"
            >
              <ChartColumn size={15} aria-hidden="true" />
              <span className="hidden sm:inline">Hisobotlar</span>
            </Link>
          )}
          <ConsoleUserMenu />
        </span>
      </motion.header>

      {/* Dam olish / bayram kuni — nima uchun hamma sonlar 0 ekanini aytadi. */}
      {canPeople && <DayOffNotice date={date} onPick={filter.setDate} className="relative z-10 mx-3 mt-2.5" />}

      {/* Panellar: chapda jadval, o'ngda kameralar va jonli sanoqlar. */}
      <motion.main
        className="console-grid relative z-10 mt-2.5 grid min-h-0 flex-1 auto-rows-[minmax(300px,auto)] grid-cols-1 gap-2.5 px-3 pb-3 lg:auto-rows-fr lg:grid-cols-4 lg:grid-rows-3"
      >
        {canPeople && (
          <GroupTablePanel
            selection={selection}
            live={groupLive}
            criteria={groupCriteria}
            canCriteria={canPeople}
            date={date}
            setDate={filter.setDate}
            isToday={isToday}
            pulse={pulse}
            expanded={expanded === 'groups'}
            onExpand={setExpanded}
            area="min-h-[420px] lg:min-h-0 lg:col-span-2 lg:row-span-3"
          />
        )}

        {canLive && (
          <CamerasPanel
            focusRequest={target?.panel === 'cameras' ? target : null}
            expanded={expanded === 'cameras'}
            onExpand={setExpanded}
            area={cn('min-h-[340px] lg:min-h-0 lg:col-span-2', canPeople ? 'lg:row-span-2' : 'lg:row-span-3')}
          />
        )}

        {canPeople && (
          <GroupStatsPanel
            selection={selection}
            live={groupLive}
            criteria={groupCriteria}
            canCriteria={canPeople}
            date={date}
            isToday={isToday}
            pulse={pulse}
            expanded={expanded === 'group-stats'}
            onExpand={setExpanded}
            area="lg:col-span-2 lg:row-span-1"
          />
        )}
      </motion.main>

      <footer className="relative z-10 flex shrink-0 items-center gap-3 px-5 pb-2 text-subtle">
        <span className="text-[10px] font-medium">{date}</span>
        <span className="ms-auto hidden text-[10px] font-medium lg:inline">Sonni bosing — kimligi · kamerani bosing — kattalashadi · Ctrl+K — qidiruv · Esc — yopadi</span>
      </footer>

      <div role="status" aria-live="assertive" className="sr-only">{announcement}</div>

      <ConsolePalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        units={[]}
        people={canPeople}
        cameras={canLive}
        onOpen={openTarget}
      />
    </div>
    </LayoutGroup>
  );
}
