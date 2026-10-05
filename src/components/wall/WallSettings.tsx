import { Check, Copy, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { buildWallQuery, PANEL_TITLES, WALL_PANELS, type WallConfig, type WallPanelId } from '../../lib/wallApi';
import { Button, cn, IconButton, Input } from '../../ui';

/** "S" tugmasi bilan ochiladigan yashirin sozlamalar. */
export function WallSettings({
  config,
  onApply,
  onClose,
}: {
  config: WallConfig;
  onApply: (cfg: WallConfig) => void;
  onClose: () => void;
}) {
  const [panels, setPanels] = useState<WallPanelId[]>(config.panels);
  const [rotate, setRotate] = useState(String(config.rotate));
  const [cameras, setCameras] = useState(config.cameras.join(','));
  const [copied, setCopied] = useState(false);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const copyTimer = useRef<number | null>(null);
  // Oyna "S" tugmasi bilan ochiladi — fokus hech qayerga ko'chmasa,
  // klaviatura bilan ishlaydigan foydalanuvchi oynaga umuman tusha olmasdi.
  useEffect(() => {
    closeRef.current?.focus();
    return () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    };
  }, []);

  const draft: WallConfig = {
    panels: panels.length ? panels : config.panels,
    rotate: Math.min(300, Math.max(5, Number(rotate) || 15)),
    cameras: cameras
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 4),
  };
  const url = `${window.location.origin}/markaz-ekran${buildWallQuery(draft)}`;

  const toggle = (p: WallPanelId) =>
    setPanels((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : WALL_PANELS.filter((x) => x === p || prev.includes(x))));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      // Oyna yopilgach taymer ishlamasin (yo'q komponentga setState).
      copyTimer.current = window.setTimeout(() => {
        copyTimer.current = null;
        setCopied(false);
      }, 1500);
    } catch {
      /* clipboard yopiq — foydalanuvchi matnni o'zi ko'chiradi */
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Ekran sozlamalari"
      className="fixed right-4 top-4 z-50 w-[360px] max-w-[calc(100vw-2rem)] rounded-card border border-border bg-surface p-4 text-sm shadow-pop animate-ui-pop-in"
    >
      <div className="mb-3 flex items-center">
        <div className="font-semibold text-fg">Ekran sozlamalari</div>
        <IconButton ref={closeRef} label="Yopish" icon={X} variant="ghost" size="sm" className="ml-auto" onClick={onClose} />
      </div>
      <div className="mb-1 text-xs font-medium text-muted">Panellar</div>
      <div className="mb-3 grid grid-cols-2 gap-1.5">
        {WALL_PANELS.map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={panels.includes(p)}
            onClick={() => toggle(p)}
            className={cn(
              'flex items-center gap-2 rounded-control border px-2.5 py-1.5 text-left',
              panels.includes(p) ? 'border-primary bg-primary-soft text-primary' : 'border-border text-muted hover:bg-surface-2',
            )}
          >
            <span className="font-mono text-xs">{p}</span>
            {PANEL_TITLES[p]}
          </button>
        ))}
      </div>
      {panels.length === 0 && (
        <p className="mb-3 text-xs text-warning">Kamida bitta panel kerak — hozirgi panellar saqlanadi.</p>
      )}
      <label className="mb-1 block text-xs font-medium text-muted" htmlFor="wall-rotate">
        Aylanish, soniya
      </label>
      <Input id="wall-rotate" type="number" min={5} max={300} value={rotate} onChange={(e) => setRotate(e.target.value)} className="mb-3" />
      <label className="mb-1 block text-xs font-medium text-muted" htmlFor="wall-cams">
        Kamera ID lari (vergul bilan, 4 tagacha)
      </label>
      <Input id="wall-cams" value={cameras} onChange={(e) => setCameras(e.target.value)} placeholder="bo'sh qoldirilsa — tasvir berayotgan birinchi 2 ta kamera" className="mb-1" />
      {/* Ortiqchasi jimgina tashlab yuborilardi — endi buni aytamiz. */}
      <p className="mb-3 text-xs text-warning" role={cameras.split(',').filter((x) => x.trim()).length > 4 ? 'status' : undefined}>
        {cameras.split(',').filter((x) => x.trim()).length > 4
          ? `Faqat birinchi 4 tasi olinadi: ${draft.cameras.join(', ')}`
          : ' '}
      </p>
      <div className="mb-3 break-all rounded-control bg-surface-2 p-2 font-mono text-xs text-muted">{url}</div>
      <div className="flex gap-2">
        <Button variant="secondary" icon={copied ? Check : Copy} onClick={copy} aria-live="polite">
          {copied ? 'Nusxalandi' : 'URL nusxa'}
        </Button>
        <Button className="ml-auto" onClick={() => onApply(draft)}>
          Qo'llash
        </Button>
      </div>
      <div className="mt-3 text-xs text-muted">S — yopish/ochish · F — to'liq ekran</div>
    </div>
  );
}
