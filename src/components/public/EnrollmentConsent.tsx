import { useEffect, useState } from 'react';
import { ArrowLeft, ChevronDown, RotateCcw, ScanFace, ShieldCheck } from 'lucide-react';
import { Button, CodeText, MicroLabel, Skeleton, SkeletonText, StatusLamp, cn, focusRing } from '../../ui';
import { Notice } from '../settings/kit';
import { ApiError } from '../../lib/apiClient';
import { fetchConsentText, type ConsentText } from '../../lib/enrollment';

interface EnrollmentConsentProps {
  /** Odam belgi qo'ydimi — sahifa uni /submit ga uzatadi. */
  onContinue: (consent: boolean) => void;
  onBack: () => void;
}

/** Yuzni skanerlashdan OLDINGI qadam: biometrik ma'lumotni qayta ishlashga
 *  rozilik. Matn serverdan olinadi (muddatlar va operator nomi server
 *  sozlamalarida) — shu sababli matnni o'qib bo'lmasa, davom etish ham
 *  mumkin emas: odam nimaga rozi bo'layotganini bilmay belgi qo'ymasligi
 *  kerak. */
export default function EnrollmentConsent({ onContinue, onBack }: EnrollmentConsentProps) {
  const [text, setText] = useState<ConsentText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchConsentText()
      .then((data) => {
        if (!cancelled) setText(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Server xatosining matni (5xx da "Internal Server Error",
        // 422 da pydantic yozuvi) ingliz tilida keladi va o'zbekcha
        // ommaviy sahifada odamga hech narsa aytmaydi.
        const serverSaid = err instanceof ApiError && err.status < 500 && err.status !== 422;
        setError(
          serverSaid
            ? (err as ApiError).message
            : "Rozilik matnini yuklab bo'lmadi. Internet aloqasini tekshirib, qayta urinib ko'ring.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (error) {
    return (
      <div className="flex flex-col gap-3">
        <Notice tone="danger">{error}</Notice>
        <Button size="lg" icon={RotateCcw} onClick={() => setAttempt((n) => n + 1)} fullWidth>
          Qayta urinish
        </Button>
        <Button variant="ghost" icon={ArrowLeft} onClick={onBack} fullWidth>
          Orqaga
        </Button>
      </div>
    );
  }

  if (!text) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Rozilik matni yuklanmoqda">
        <div className="flex items-start gap-3">
          <Skeleton className="h-9 w-9 shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
        <SkeletonText lines={3} />
        <Skeleton className="h-11 w-full" />
      </div>
    );
  }

  const canContinue = agreed || !text.required;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-primary/25 bg-primary-soft text-primary">
          <ShieldCheck size={18} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <MicroLabel>Bosqich 3 — Rozilik</MicroLabel>
          <h2 className="mt-0.5 text-[15px] font-semibold leading-snug text-fg">{text.title}</h2>
        </div>
      </div>

      {/* Hujjat rekvizitlari: kim qayta ishlaydi, qaysi matn, majburiymi. */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-y border-border py-2">
        <span className="col-span-2 flex min-w-0 flex-col gap-0.5">
          <MicroLabel>Ma&apos;lumotlar operatori</MicroLabel>
          <span className="truncate text-[13px] font-medium text-fg">{text.controller}</span>
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <MicroLabel>Matn versiyasi</MicroLabel>
          <CodeText className="truncate text-[13px] font-semibold text-fg">{text.version}</CodeText>
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <MicroLabel>Rozilik holati</MicroLabel>
          <StatusLamp
            status={agreed ? 'ok' : text.required ? 'alert' : 'idle'}
            label={agreed ? 'Berilgan' : text.required ? 'Berilmagan' : 'Ixtiyoriy'}
          />
        </span>
      </div>

      <p className="text-[13px] leading-relaxed text-muted">
        Kameralar sizni tanishi uchun yuzingiz tasviri va undan olingan raqamli shablon saqlanadi. Ular faqat davomat va bino xavfsizligi uchun
        ishlatiladi, rozilikni esa istalgan vaqtda qaytarib olishingiz mumkin.
      </p>

      <div className="overflow-hidden rounded-control border border-border">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls="consent-full-text"
          className={cn('flex min-h-11 w-full items-center justify-between gap-2 bg-surface-2 px-3.5 py-2.5 text-left text-sm font-medium text-primary hover:bg-surface-3', focusRing)}
        >
          {expanded ? "To'liq matnni yashirish" : "To'liq matnni o'qish"}
          <ChevronDown size={16} aria-hidden="true" className={cn('shrink-0 transition-transform', expanded && 'rotate-180')} />
        </button>
        {expanded && (
          <div id="consent-full-text" className="max-h-72 space-y-3 overflow-y-auto border-t border-border px-3.5 py-3">
            {text.sections.map((section) => (
              <div key={section.title}>
                <MicroLabel className="intel-micro-wrap block !text-fg">{section.title}</MicroLabel>
                <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{section.body}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <label
        className={cn(
          'flex cursor-pointer items-start gap-3 rounded-control border p-3.5 transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-primary/40',
          agreed ? 'border-primary bg-primary-soft' : 'border-border bg-surface hover:border-border-strong',
        )}
      >
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer accent-primary" />
        <span className="min-w-0 text-[13px] leading-relaxed text-fg">
          <MicroLabel className="block !text-fg">Roziman</MicroLabel>
          <span className="mt-0.5 block">{text.statement}</span>
        </span>
      </label>

      <div className="flex flex-col gap-1.5">
        <Button variant="primary" size="lg" icon={ScanFace} onClick={() => onContinue(agreed)} disabled={!canContinue} fullWidth>
          Yuzni skanerlashga o&apos;tish
        </Button>
        {!canContinue && <p className="text-center text-xs text-muted">Davom etish uchun rozilik belgisini qo&apos;ying</p>}
      </div>
      <Button variant="ghost" icon={ArrowLeft} onClick={onBack} fullWidth>
        Orqaga
      </Button>
    </div>
  );
}
