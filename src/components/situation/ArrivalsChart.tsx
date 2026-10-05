import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { cn } from '../../ui';
import { useSharedNow } from '../../lib/sharedClock';
import {
  arrivalBars,
  barTitle,
  clockMinutes,
  formatClock,
  tashkentMinutes,
  timeFraction,
  visibleBars,
  type HourBucket,
} from '../../lib/arrivals';
import type { PersonType } from '../../lib/situationApi';

/**
 * Kelish oqimi: soat bo'yicha nechta odam kelgani (kunning birinchi
 * ko'rinishi), har ustunda o'z vaqtida (yashil) va kech (sariq) qismi,
 * kechikish chegarasi (ish vaqti sozlamasidan) va bugun — "hozir" belgisi.
 * Ustun bosilsa — o'sha soatda kelganlar ro'yxati (onPick).
 *
 * SVG piksellarda chiziladi (kenglik konteynerdan o'lchanadi): matn har
 * kenglikda bir xil o'lchamda qoladi, cho'zilmaydi.
 */

const TOP = 34; // chiziqlar yozuvi uchun joy
const BOTTOM = 22; // soat yozuvlari
const SIDE = 6;
// Grafik panelda qolgan joyni egallaydi, lekin shu oraliqda qoladi.
const MIN_HEIGHT = 112;
const MAX_HEIGHT = 360;
// O'lchov kelguncha — eng kichik balandlik: zaxira konteynerdan baland
// bo'lsa, SVG pastdagi izoh ustiga chiqib qolardi (2026-10-06 skrinshot).
const FALLBACK = { width: 520, height: MIN_HEIGHT };

/** Konteyner o'lchami (ResizeObserver; jsdom va eski brauzerda — zaxira). */
function useSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState(FALLBACK);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    // contentRect — CSS o'lchami; getBoundingClientRect esa panel ochilish
    // animatsiyasining transform'i (scale) bilan buziladi.
    const apply = (rawWidth: number, rawHeight: number) => {
      const width = Math.round(rawWidth);
      const height = Math.round(rawHeight);
      if (width > 0) setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    };
    apply(element.clientWidth, element.clientHeight);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[entries.length - 1]?.contentRect;
      if (box) apply(box.width, box.height);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

export default function ArrivalsChart({
  buckets,
  who,
  lateAfter,
  isToday,
  untimed = 0,
  onPick,
  className,
}: {
  buckets: readonly HourBucket[];
  who: PersonType;
  /** Kechikish chegarasi "HH:MM" (overview.lateAfterStudents / lateAfterStaff). */
  lateAfter: string | null | undefined;
  isToday: boolean;
  /** Kelgan, lekin kelish vaqti noma'lum (HEMIS davomati, qo'lda kiritilgan)
   *  — soatlarga taqsimlanmaydi, sarlavhada alohida aytiladi. */
  untimed?: number;
  onPick?: (hour: number) => void;
  className?: string;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const width = size.width;
  // Konteynerdan baland bo'lmaydi (u CSS bilan kamida MIN_HEIGHT).
  const HEIGHT = Math.min(MAX_HEIGHT, size.height > 0 ? size.height : MIN_HEIGHT);
  const clipBase = useId();
  const now = useSharedNow(isToday);
  const nowMinutes = tashkentMinutes(now);
  const bars = visibleBars(arrivalBars(buckets, who), { isToday, nowHour: Math.floor(nowMinutes / 60) });
  const [hovered, setHovered] = useState<number | null>(null);

  const people = who === 'xodim' ? 'xodim' : 'talaba';
  const untimedText = untimed > 0 ? `${untimed.toLocaleString('ru-RU')} kishining kelish vaqti noma’lum` : null;
  if (bars.length === 0) {
    return (
      <div className={cn('rounded-control border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted', className)}>
        {untimedText
          ? `Kelish vaqtlari yozilmagan — ${untimedText} (HEMIS davomati yoki qo‘lda kiritilgan)`
          : isToday
            ? `Bugun hali birorta ${people} kamerada tanilmagan`
            : `Bu kuni ${people}larning kelish yozuvi yo‘q`}
      </div>
    );
  }

  const plotWidth = Math.max(120, width - SIDE * 2);
  const slot = plotWidth / bars.length;
  const barWidth = Math.min(44, Math.max(10, slot * 0.62));
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const max = Math.max(...bars.map((b) => b.total), 1);
  const yOf = (value: number) => (value / max) * plotHeight;
  const xOfFraction = (fraction: number) => SIDE + fraction * plotWidth;

  const lateMinutes = clockMinutes(lateAfter);
  const lateFraction = timeFraction(lateMinutes, bars);
  const nowFraction = isToday ? timeFraction(nowMinutes, bars) : null;
  const lateX = lateFraction === null ? null : xOfFraction(lateFraction);
  const nowX = nowFraction === null ? null : xOfFraction(nowFraction);
  // Ikki yozuv bir-biriga tegmasin: yaqin bo'lsa "hozir" ikkinchi qatorga tushadi.
  const nowLabelY = lateX !== null && nowX !== null && Math.abs(nowX - lateX) < 120 ? 26 : 12;
  const labelAnchor = (x: number) => (x > width - 110 ? 'end' : 'start');
  const labelDx = (x: number) => (x > width - 110 ? -5 : 5);
  const total = bars.reduce((sum, b) => sum + b.total, 0);
  const late = bars.reduce((sum, b) => sum + b.late, 0);

  function onKey(event: KeyboardEvent<SVGGElement>, hour: number) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onPick?.(hour);
    }
  }

  return (
    <div className={cn('flex flex-col rounded-control border border-border bg-surface px-3 pb-2 pt-2.5', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold text-fg">Kelish oqimi</span>
        <span className="text-right text-[11px] text-muted">
          {untimedText ? (
            <span
              title="HEMIS davomati yoki qo‘lda kiritilgan yozuvlar: kelgan, lekin kamera vaqtini yozmagan — soatlarga taqsimlanmaydi"
              className="cursor-help underline decoration-dotted decoration-subtle underline-offset-2"
            >
              jami {(total + untimed).toLocaleString('ru-RU')} · {untimedText}
            </span>
          ) : (
            'soatlar bo‘yicha'
          )}
        </span>
      </div>
      {/* O'lchanadigan maydon: kenglik ham, balandlik ham shundan (min/max bilan). */}
      <div ref={ref} className="relative mt-1 min-h-[112px] w-full flex-1 overflow-hidden">
        <svg
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="group"
          aria-label={`Soatlar bo‘yicha kelganlar: jami ${total}, shundan ${late} tasi kech${untimed > 0 ? `; yana ${untimed} kishining kelish vaqti noma’lum` : ''}`}
          className="absolute inset-x-0 top-0 block select-none overflow-visible"
        >
          <line x1={SIDE} x2={width - SIDE} y1={TOP + plotHeight} y2={TOP + plotHeight} className="stroke-border" strokeWidth={1} />

          {bars.map((bar, index) => {
            const cx = SIDE + slot * index + slot / 2;
            const x = cx - barWidth / 2;
            const totalHeight = yOf(bar.total);
            const onTimeHeight = yOf(bar.onTime);
            const yTop = TOP + plotHeight - totalHeight;
            const clipId = `${clipBase}-${bar.hour}`;
            const clickable = Boolean(onPick) && bar.total > 0;
            const dimmed = hovered !== null && hovered !== bar.hour;
            return (
              <g
                key={bar.hour}
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-label={barTitle(bar)}
                onClick={clickable ? () => onPick?.(bar.hour) : undefined}
                onKeyDown={clickable ? (event) => onKey(event, bar.hour) : undefined}
                onMouseEnter={() => setHovered(bar.hour)}
                onMouseLeave={() => setHovered(null)}
                className={cn('outline-none transition-opacity focus-visible:opacity-100', clickable && 'cursor-pointer', dimmed && 'opacity-60')}
              >
                <title>{barTitle(bar)}</title>
                {/* Butun ustun oralig'i bosiladi — kichik ustunni ham topish oson. */}
                <rect x={SIDE + slot * index} y={TOP - 6} width={slot} height={plotHeight + 6} fill="transparent" />
                {bar.total > 0 && (
                  <>
                    <clipPath id={clipId}>
                      <rect x={x} y={yTop} width={barWidth} height={Math.max(totalHeight, 2)} rx={Math.min(7, barWidth / 3)} />
                    </clipPath>
                    <g clipPath={`url(#${clipId})`}>
                      <rect x={x} y={yTop} width={barWidth} height={Math.max(totalHeight, 2)} className="fill-warning" />
                      <rect x={x} y={TOP + plotHeight - onTimeHeight} width={barWidth} height={onTimeHeight} className="fill-success" />
                    </g>
                    <text x={cx} y={yTop - 5} textAnchor="middle" className="fill-fg text-[11px] font-semibold tabular-nums">
                      {bar.total}
                    </text>
                  </>
                )}
                <text x={cx} y={HEIGHT - 6} textAnchor="middle" className="fill-muted text-[11px] tabular-nums">
                  {String(bar.hour).padStart(2, '0')}
                </text>
              </g>
            );
          })}

          {lateX !== null && lateMinutes !== null && (
            <g aria-hidden="true">
              <line x1={lateX} x2={lateX} y1={TOP - 14} y2={TOP + plotHeight} className="stroke-danger" strokeWidth={1.25} strokeDasharray="4 3" />
              <text x={lateX + labelDx(lateX)} y={12} textAnchor={labelAnchor(lateX)} className="fill-danger text-[11px] font-medium">
                {formatClock(lateMinutes)} kechikish
              </text>
            </g>
          )}
          {nowX !== null && (
            <g aria-hidden="true">
              <line x1={nowX} x2={nowX} y1={nowLabelY + 4} y2={TOP + plotHeight} className="stroke-primary" strokeWidth={1.25} strokeDasharray="2 3" />
              <text x={nowX + labelDx(nowX)} y={nowLabelY} textAnchor={labelAnchor(nowX)} className="fill-primary text-[11px] font-medium tabular-nums">
                hozir {formatClock(nowMinutes)}
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-[3px] bg-success" aria-hidden="true" /> o‘z vaqtida
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-[3px] bg-warning" aria-hidden="true" /> kech
          {lateMinutes !== null ? ` (${formatClock(lateMinutes)} dan keyin)` : ''}
        </span>
        {onPick && <span className="ms-auto">Ustunni bosing — o‘sha soatda kelganlar</span>}
      </div>
    </div>
  );
}

