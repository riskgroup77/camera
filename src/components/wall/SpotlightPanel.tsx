import { Sparkles } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { fitGrid, type SpotlightDetail } from '../../lib/wallApi';
import { CodeText, MicroLabel, cn } from '../../ui';
import { WallFace, WallPanel, WallRing } from './primitives';

function useSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) => (Math.abs(s.w - width) < 1 && Math.abs(s.h - height) < 1 ? s : { w: width, h: height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

function FaceGrid({ detail }: { detail: SpotlightDetail }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const gap = 10;
  const faces = detail.faces;
  const grid = fitGrid(faces.length, size.w, size.h, 0.74, gap);
  const tile = Math.min(grid.tile, 260);
  const showNames = tile >= 64;
  return (
    <div ref={ref} className="min-h-0 flex-1">
      {size.w > 0 && (
        <div
          className="grid content-center justify-center"
          style={{ gridTemplateColumns: `repeat(${grid.cols}, ${tile}px)`, gap, height: '100%' }}
        >
          {faces.map((f) => {
            const waiting = f.status === 'kutilmoqda' || f.status === 'malumot_yoq' || f.status === 'dam_olish';
            return (
              <div key={f.id} className="flex min-w-0 flex-col items-center" style={{ fontSize: Math.max(9, Math.min(15, tile / 9)) }}>
                <WallFace
                  photoUrl={f.photoUrl}
                  initials={f.initials}
                  status={f.status}
                  dim={waiting}
                  className="aspect-square w-full"
                />
                {showNames && (
                  <div className="mt-[0.35em] w-full text-center leading-tight">
                    <div className="truncate font-medium text-fg">{f.fullName.split(' ').slice(0, 2).join(' ')}</div>
                    <div className={f.noFace && !f.checkIn ? 'text-warning' : 'intel-code text-muted'}>
                      {f.checkIn ?? (f.noFace ? 'yuzsiz' : '—')}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SpotlightView({ detail }: { detail: SpotlightDetail }) {
  const c = detail.counts;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-[0.9em] flex shrink-0 items-center gap-[1em]">
        <WallRing value={c.rate} size={5} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[1.9em] font-semibold leading-tight tracking-tight text-fg">{detail.name}</div>
          <MicroLabel className="mt-[0.3em] block">{detail.subtitle}</MicroLabel>
        </div>
        <div className="flex shrink-0 gap-[1.2em] text-right">
          <Stat label="keldi" value={c.present} tone="text-success" />
          <Stat label="kech" value={c.late} tone="text-warning" />
          <Stat label="kelmadi" value={c.absent} tone="text-danger" />
          <Stat label="jami" value={c.total} tone="text-fg" />
        </div>
      </div>
      {detail.faces.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-muted">Ro'yxat bo'sh</div>
      ) : (
        <FaceGrid detail={detail} />
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div>
      <div className={cn('intel-code text-[1.9em] font-semibold leading-none', tone)}>{value}</div>
      <MicroLabel className="mt-[0.4em] block !text-[0.6em]">{label}</MicroLabel>
    </div>
  );
}

/**
 * Navbatdagi bo'linma/guruh yuzlari. Ikki qatlamli cross-fade: yangi
 * tafsilot kelganda eskisi 0.8 s davomida so'nadi.
 */
export function SpotlightPanel({
  detail,
  index,
  total,
  rotateS,
  cycleKey,
}: {
  detail: SpotlightDetail | null;
  index: number;
  total: number;
  rotateS: number;
  cycleKey: number;
}) {
  const [layers, setLayers] = useState<SpotlightDetail[]>(detail ? [detail] : []);
  useEffect(() => {
    if (!detail) return;
    setLayers((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.key === detail.key) return [...prev.slice(0, -1), detail];
      return [...(last ? [last] : []), detail];
    });
    const t = window.setTimeout(() => setLayers((prev) => prev.slice(-1)), 900);
    return () => window.clearTimeout(t);
  }, [detail]);

  return (
    <WallPanel
      area="C"
      title="Diqqat markazida"
      icon={<Sparkles />}
      aside={total > 0 ? <CodeText className="text-[0.95em]">{index + 1} / {total}</CodeText> : null}
    >
      {layers.length === 0 ? (
        // Ro'yxat bor, lekin tafsilot hali kelmagan — bu "hech narsa yo'q"
        // emas, "yuklanmoqda". Ikkalasini bir xil yozish chalg'itardi.
        <div className="flex flex-1 flex-col items-center justify-center text-center text-muted">
          <Sparkles className="mb-[0.5em] h-[2.5em] w-[2.5em] opacity-50" />
          <div>{total > 0 ? 'Yuklanmoqda…' : "Bo'linma yo'q"}</div>
        </div>
      ) : (
        <div className="relative min-h-0 flex-1">
          {layers.map((l, i) => (
            <div
              key={l.key}
              className={cn(
                'absolute inset-0 transition-opacity duration-700 ease-out',
                i === layers.length - 1 ? 'wall-fade-in opacity-100' : 'opacity-0',
              )}
            >
              <SpotlightView detail={l} />
            </div>
          ))}
        </div>
      )}
      {/* Panelda `overflow-hidden` bor: manfiy `bottom` chizig'ini butunlay
          kesib tashlardi — aylanish taymeri ekranda hech qachon ko'rinmasdi. */}
      {total > 1 && (
        <div className="absolute inset-x-0 bottom-0 h-[0.2em] overflow-hidden rounded-full bg-surface-3">
          <div
            key={cycleKey}
            className="wall-progress h-full bg-primary"
            style={{ animationDuration: `${rotateS}s` }}
          />
        </div>
      )}
    </WallPanel>
  );
}
