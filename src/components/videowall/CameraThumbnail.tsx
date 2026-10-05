import { useEffect, useRef, useState } from 'react';
import { Loader2, VideoOff } from 'lucide-react';
import { api } from '../../lib/apiClient';

/** Qavat grididagi bitta kamera kadri (jonli video EMAS).
 *
 * Nega rasm: 24 kamerali qavatda 24 ta HLS oqimi MediaMTX'da 24 ta
 * ffmpeg transkodi degani — oldingi monitoring sahifasi har tomoshabinga
 * 9 ta oqim ochardi. Rasm esa AI baribir oladigan kadrdan tayyorlanadi
 * (backend: app/services/thumbnail_cache.py), ya'ni kameraga qo'shimcha
 * ulanish qilmaydi. Jonli video faqat operator tanlagan bitta kamerada.
 *
 * Yana ikki tejamkorlik shu yerda:
 * - ekranda ko'rinmayotgan karta umuman so'rov yubormaydi
 *   (IntersectionObserver);
 * - varaq fonga o'tsa yangilanish to'xtaydi.
 *
 * Rasm Bearer token bilan olinadi, shuning uchun oddiy <img src> emas,
 * fetch -> blob: /api/public/* endpointlari token talab qiladi va
 * brauzer <img> so'roviga sarlavha qo'sha olmaydi. */
export default function CameraThumbnail({
  cameraId,
  refreshMs = 10_000,
  className = '',
  alt = '',
}: {
  cameraId: string;
  refreshMs?: number;
  className?: string;
  alt?: string;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const [visible, setVisible] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'empty'>('loading');

  useEffect(() => {
    const node = holder.current;
    if (!node || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((entry) => entry.isIntersecting)),
      { rootMargin: '150px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let timer: number | undefined;

    function schedule(ms: number) {
      timer = window.setTimeout(() => void load(), ms);
    }

    async function load() {
      if (cancelled) return;
      if (document.visibilityState === 'hidden') {
        schedule(refreshMs);
        return;
      }
      try {
        const blob = await api.blob(`/api/public/cameras/${cameraId}/thumbnail`);
        if (cancelled) return;
        const next = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setSrc(next);
        setState('ready');
        schedule(refreshMs);
      } catch {
        if (cancelled) return;
        // 404 = "hali kadr yo'q" (xato emas). Eski rasm bo'lsa u qoladi,
        // bo'lmasa joy egallovchi chiziladi; keyingi urinish siyrakroq.
        setState((current) => (current === 'ready' ? current : 'empty'));
        schedule(refreshMs * 3);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [cameraId, visible, refreshMs]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    },
    [],
  );

  return (
    <div ref={holder} className={`relative overflow-hidden bg-neutral-900 ${className}`}>
      {src ? (
        <img src={src} alt={alt} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-white/35">
          {state === 'empty' ? <VideoOff size={18} aria-hidden="true" /> : <Loader2 size={18} aria-hidden="true" className="animate-spin" />}
          <span className="text-[10px] font-medium">
            {state === 'empty' ? "Kadr yo'q" : "Yuklanmoqda"}
          </span>
        </div>
      )}
    </div>
  );
}
