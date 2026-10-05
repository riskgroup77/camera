import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { ScanFace } from 'lucide-react';
import { cn } from '../../ui';
import { encodeQr, qrPath } from '../../lib/qr';
import { branding } from '../../lib/branding';

/** QR-kod (SVG, tashqi kutubxonasiz). Har doim oq fonda qora — skanerlar uchun. */
export function QrCode({ value, className, title = 'QR-kod' }: { value: string; className?: string; title?: string }) {
  const qr = useMemo(() => {
    try {
      return encodeQr(value);
    } catch {
      return null;
    }
  }, [value]);
  if (!qr) return <p className={cn('text-xs text-danger', className)}>Havola QR uchun juda uzun</p>;
  const dim = qr.size + 8;
  return (
    <svg viewBox={`0 0 ${dim} ${dim}`} className={className} role="img" aria-label={title} shapeRendering="crispEdges">
      <rect width={dim} height={dim} fill="#fff" />
      <path d={qrPath(qr.modules, 4)} fill="#000" />
    </svg>
  );
}

const STEPS = [
  'Telefon kamerasi bilan QR-kodni skanerlang.',
  'JSHSHIR (pasportdagi 14 raqam) bilan o‘zingizni toping.',
  'Yuzingizni yorug‘ joyda, ko‘zoynaksiz skanerlang.',
];

/** Guruh uchun chop etiladigan karta: guruh nomi, QR va qisqa ko'rsatma.
 *  Ekranda ham xuddi shu ko'rinishda (oldindan ko'rish) — doim yorug' mavzuda. */
export function EnrollQrCard({
  group,
  url,
  faculty,
  missing,
  className,
}: {
  group: string;
  url: string;
  faculty?: string | null;
  missing?: number;
  className?: string;
}) {
  return (
    <div data-theme="light" className={cn('enroll-card flex flex-col items-center rounded-card border border-border bg-surface p-6 text-center text-fg', className)}>
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{branding.orgName}</p>
      <p className="mt-3 inline-flex items-center gap-2 text-sm font-medium text-primary">
        <ScanFace size={18} aria-hidden="true" />
        Yuzni ro&apos;yxatdan o&apos;tkazish
      </p>
      <h2 className="enroll-card-group mt-1 text-4xl font-bold tracking-tight">{group}</h2>
      {faculty && <p className="mt-1 text-sm text-muted">{faculty}</p>}
      <QrCode value={url} className="enroll-card-qr mt-5 aspect-square w-56 max-w-full" title={`${group} guruhi uchun ro'yxatdan o'tish havolasi`} />
      <ol className="mt-5 w-full max-w-xs space-y-1.5 text-left text-sm">
        {STEPS.map((s, i) => (
          <li key={s} className="flex gap-2">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-xs text-muted">1 daqiqa vaqt oladi. Shundan so&apos;ng kameralar davomatingizni o&apos;zi belgilaydi.</p>
      <p className="mt-3 max-w-full break-all font-mono text-[10px] text-subtle">{url}</p>
      {missing !== undefined && missing > 0 && <p className="enroll-card-screen-only mt-2 text-xs text-muted">Hali topshirmagan: {missing} talaba</p>}
    </div>
  );
}

const PRINT_CSS = `
@media screen { .enroll-print-root { display: none !important; } }
@media print {
  @page { size: A5 portrait; margin: 8mm; }
  html, body { background: #fff !important; }
  body > *:not(.enroll-print-root) { display: none !important; }
  .enroll-print-root { display: block !important; }
  .enroll-print-root .enroll-card { border: 0 !important; box-shadow: none !important; padding: 0 !important; break-inside: avoid; page-break-after: always; min-height: 180mm; justify-content: center; }
  .enroll-print-root .enroll-card:last-child { page-break-after: auto; }
  .enroll-print-root .enroll-card-group { font-size: 40pt; }
  .enroll-print-root .enroll-card-qr { width: 85mm !important; }
  .enroll-print-root .enroll-card-screen-only { display: none !important; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}`;

/** Chop etish: kartalarni body'ga portal qiladi va brauzer chop etish oynasini ochadi. */
export function EnrollPrintPortal({
  cards,
  onDone,
}: {
  cards: Array<{ group: string; url: string; faculty?: string | null }> | null;
  onDone: () => void;
}) {
  useEffect(() => {
    if (!cards?.length) return;
    const after = () => onDone();
    window.addEventListener('afterprint', after);
    // Chrome'da print() bloklaydi — qaytgach portal yopiladi (afterprint bo'lmasa ham).
    const id = window.setTimeout(() => {
      window.print();
      onDone();
    }, 50);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener('afterprint', after);
    };
  }, [cards, onDone]);
  if (!cards?.length) return null;
  return createPortal(
    <div className="enroll-print-root">
      <style>{PRINT_CSS}</style>
      {cards.map((c) => (
        <EnrollQrCard key={c.group} group={c.group} url={c.url} faculty={c.faculty} />
      ))}
    </div>,
    document.body,
  );
}
