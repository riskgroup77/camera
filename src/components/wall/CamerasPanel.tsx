import { Cctv } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import LiveVideoPlayer from '../LiveVideoPlayer';
import { fetchAllPages } from '../../lib/apiClient';
import { isCameraOnline, pruneCameraIds } from '../../lib/videoWall';
import type { CameraFeed } from '../../types';
import { WallPanel } from './primitives';

/** 2–4 jonli kamera. Kanal kengligini tejash uchun faqat tanlangan
 *  (yoki birinchi aloqadagi) kameralar; aloqadagi kamera yo'q bo'lsa panel
 *  umuman chiqmaydi (`onEmpty`).
 *
 *  `onPrune` — sozlamalarda o'chirilgan kamera ekran sozlamasida abadiy
 *  osilib qolmasligi uchun: ro'yxat ishonchli kelganda, endi mavjud
 *  bo'lmagan identifikatorlarsiz ro'yxat qaytariladi. */
export function CamerasPanel({
  ids,
  onAvailability,
  onPrune,
}: {
  ids: string[];
  onAvailability: (has: boolean) => void;
  onPrune?: (ids: string[]) => void;
}) {
  const [cams, setCams] = useState<CameraFeed[] | null>(null);
  /** Oxirgi xatosiz va bo'sh bo'lmagan javob — faqat shu asosda tozalanadi. */
  const [knownIds, setKnownIds] = useState<ReadonlySet<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAllPages<CameraFeed>('/api/public/cameras', undefined, {}, 500)
        .then((items) => {
          if (cancelled) return;
          setCams(items);
          if (items.length > 0) setKnownIds(new Set(items.map((c) => c.id)));
        })
        .catch(() => {
          // Birinchi so'rov xato bersa `cams` abadiy `null` bo'lib qolardi:
          // `onAvailability` hech qachon chaqirilmas, devor joylashuvida
          // "F" maydoni bo'm-bo'sh teshik bo'lib turaverardi. Bo'sh
          // ro'yxat "kamera yo'q" degan aniq javob beradi; keyingi
          // muvaffaqiyatli so'rov panelni qaytaradi.
          if (!cancelled) setCams((prev) => prev ?? []);
        });
    void load();
    const t = window.setInterval(load, 5 * 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!onPrune || ids.length === 0) return;
    const next = pruneCameraIds(ids, knownIds);
    if (next !== ids) onPrune([...next]);
  }, [ids, knownIds, onPrune]);

  const picked = useMemo(() => {
    const online = (cams ?? []).filter((c) => isCameraOnline(c) && c.streamUrl);
    if (!ids.length) return online.slice(0, 2);
    // Indeks bo'yicha: ilgari har bir id uchun butun ro'yxat qidirilardi.
    const byId = new Map(online.map((c) => [c.id, c]));
    return ids.map((id) => byId.get(id)).filter((c): c is CameraFeed => Boolean(c));
  }, [cams, ids]);
  const has = picked.length > 0;

  useEffect(() => {
    if (cams) onAvailability(has);
  }, [cams, has, onAvailability]);

  if (!has) return null;
  return (
    <WallPanel area="F" title="Jonli kameralar" icon={<Cctv />}>
      <div
        className="grid min-h-0 flex-1 gap-[0.6em]"
        style={{ gridTemplateRows: `repeat(${picked.length > 2 ? Math.ceil(picked.length / 2) : picked.length}, minmax(0, 1fr))`, gridTemplateColumns: picked.length > 2 ? '1fr 1fr' : '1fr' }}
      >
        {picked.map((c, i) => (
          <div key={c.id} className="intel-grid relative min-h-0 overflow-hidden rounded-[2px] border border-border bg-surface-3">
            <LiveVideoPlayer streamUrl={c.streamUrl} fit="cover" className="absolute inset-0 h-full w-full" startDelayMs={i * 800} />
            <div className="intel-code absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-[0.7em] pb-[0.4em] pt-[1.2em] text-[0.75em] text-white">
              {c.name}
              {c.building ? <span className="opacity-70"> · {c.building}</span> : null}
            </div>
          </div>
        ))}
      </div>
    </WallPanel>
  );
}
