import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { config, isBackendConfigured } from '../../lib/config';
import type { LiveStatus } from '../../lib/realtime';
import { IconButton, cn, focusRing, type Crumb } from '../../ui';
import { MicroLabel, StatusLamp, type IntelStatus } from '../../ui/intel';

const TASHKENT_TIME = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Tashkent',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/**
 * Toshkent vaqti bo'yicha jonli soat.
 *
 * Taymer faqat yorliq (tab) ko'rinib turganda ishlaydi: fonga o'tgan
 * oyna sekundiga bir marta qayta chizilib turmaydi, qaytib ko'ringanda
 * esa vaqt darhol to'g'rilanadi.
 */
export function LiveClock({ seconds = false, className }: { seconds?: boolean; className?: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let id: number | null = null;
    const tick = () => setNow(new Date());
    const start = () => {
      if (id !== null) return;
      id = window.setInterval(tick, seconds ? 1000 : 10_000);
    };
    const stop = () => {
      if (id === null) return;
      window.clearInterval(id);
      id = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stop();
      } else {
        tick();
        start();
      }
    };
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [seconds]);
  const text = TASHKENT_TIME.format(now);
  const shown = seconds ? text : text.slice(0, 5);
  return (
    <time
      className={cn('intel-code font-semibold tabular-nums text-fg', className)}
      dateTime={now.toISOString()}
      aria-label={`Toshkent vaqti ${shown}`}
      title="Toshkent vaqti (UTC+5)"
    >
      {shown}
    </time>
  );
}

type HealthState = 'ok' | 'degraded' | 'down' | 'offline' | 'demo' | 'checking';

const HEALTH_META: Record<HealthState, { status: IntelStatus; label: string }> = {
  ok: { status: 'ok', label: 'Tizim faol' },
  degraded: { status: 'warn', label: 'Qisman ishlayapti' },
  down: { status: 'alert', label: "Server bilan aloqa yo'q" },
  offline: { status: 'alert', label: "Internet yo'q" },
  demo: { status: 'idle', label: 'Demo rejim' },
  checking: { status: 'idle', label: 'Tekshirilmoqda' },
};

const CHECK_LABELS: Record<string, string> = {
  database: "Ma'lumotlar bazasi",
  storage: 'Fayl ombori',
  video_gateway: 'Video shlyuz',
};

/** Tizim holati chirog'i: backend /health har daqiqada tekshiriladi. */
export function SystemStatus({ showLabel = true }: { showLabel?: boolean }) {
  const [state, setState] = useState<HealthState>(isBackendConfigured ? 'checking' : 'demo');
  const [failing, setFailing] = useState<string[]>([]);

  useEffect(() => {
    if (!isBackendConfigured) return;
    let cancelled = false;
    let controller: AbortController | null = null;

    async function check() {
      if (!navigator.onLine) {
        setState('offline');
        return;
      }
      controller?.abort();
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 10_000);
      try {
        const res = await fetch(`${config.apiBaseUrl}/health`, { signal: controller.signal, cache: 'no-store' });
        // Javob: {"status":"degraded","database":"ok","storage":"ok","video_gateway":"unreachable"}
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (cancelled) return;
        const checks = (typeof body.checks === 'object' && body.checks ? body.checks : body) as Record<string, unknown>;
        const bad = Object.entries(checks)
          .filter(([key, value]) => key !== 'status' && typeof value === 'string' && value !== 'ok')
          .map(([key]) => CHECK_LABELS[key] ?? key);
        setFailing(bad);
        setState(res.ok ? 'ok' : bad.length > 0 ? 'degraded' : 'down');
      } catch {
        if (!cancelled) setState(navigator.onLine ? 'down' : 'offline');
      } finally {
        window.clearTimeout(timeout);
      }
    }

    void check();
    // Fonda turgan yorliq /health'ni chaqirmaydi; qaytib ko'ringanda
    // darhol bir marta tekshiriladi (holat eskirib qolmasin).
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void check();
    }, 60_000);
    const recheck = () => void check();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void check();
    };
    window.addEventListener('online', recheck);
    window.addEventListener('offline', recheck);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(id);
      window.removeEventListener('online', recheck);
      window.removeEventListener('offline', recheck);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  const meta = HEALTH_META[state];
  const detail = failing.length > 0 ? `${meta.label}: ${failing.join(', ')} ishlamayapti` : meta.label;

  return (
    <span className="inline-flex shrink-0 items-center" title={detail} role="status" aria-label={detail}>
      <StatusLamp status={meta.status} label={showLabel ? meta.label : 'Tizim'} pulse={state === 'ok'} />
    </span>
  );
}

const LIVE_META: Record<LiveStatus, { status: IntelStatus; label: string; detail: string; pulse?: boolean }> = {
  live: { status: 'ok', label: 'Jonli', detail: 'Jonli yangilanish ishlayapti', pulse: true },
  connecting: { status: 'warn', label: 'Ulanmoqda', detail: 'Jonli yangilanish uzildi — qayta ulanmoqda' },
  paused: { status: 'alert', label: "To'xtadi", detail: "Jonli yangilanish to'xtadi — sahifani yangilang" },
  off: { status: 'idle', label: "Yo'q", detail: "Jonli yangilanish yoqilmagan" },
};

/**
 * Ulanish chirog'i — RANG YOLG'IZ QOLMAYDI: yonida doim so'z turadi.
 *
 * Bunisiz ekran jonli ko'rinardi, lekin emas edi: ulanish uzilganda
 * ro'yxat shunchaki yangilanishdan to'xtardi va operator eski holatga
 * qarab "tinch" deb o'ylab o'tirardi.
 */
export function ConnectionLamp({ status, className }: { status: LiveStatus; className?: string }) {
  const meta = LIVE_META[status] ?? LIVE_META.off;
  return (
    <span className={cn('inline-flex shrink-0 items-center', className)} role="status" title={meta.detail} aria-label={meta.detail}>
      <StatusLamp status={meta.status} label={meta.label} pulse={meta.pulse} />
    </span>
  );
}

export function EventsBell({ count, onOpen }: { count: number; onOpen: () => void }) {
  return <IconButton icon={Bell} label={count > 0 ? `${count} ta yangi hodisa` : 'Hodisalar'} badge={count} onClick={onOpen} />;
}

/** Non-yo'l — asboblar panelidagi manzil chizig'i: bosh harfli monoshrift,
 *  bo'laklar orasida "/" belgisi. Telefonda faqat oxirgi bo'lak. */
export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  if (crumbs.length === 0) return null;
  return (
    <nav aria-label="Non-yo'l" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${index}`} className={cn('flex min-w-0 items-center gap-1.5', !last && 'hidden md:flex')}>
              {crumb.to && !last ? (
                <Link to={crumb.to} className={cn('min-w-0 truncate transition-colors hover:text-fg', focusRing)}>
                  <MicroLabel>{crumb.label}</MicroLabel>
                </Link>
              ) : (
                <span className={cn('min-w-0 truncate', last && 'font-semibold')} aria-current={last ? 'page' : undefined}>
                  <MicroLabel className={last ? '!text-fg' : undefined}>{crumb.label}</MicroLabel>
                </span>
              )}
              {!last && (
                <span className="intel-code shrink-0 text-[11px] text-subtle" aria-hidden="true">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
