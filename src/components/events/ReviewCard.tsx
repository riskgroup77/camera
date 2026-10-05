import { useEffect, useState } from 'react';
import { Check, FlaskConical, ImageOff, UserCheck, X } from 'lucide-react';
import { Badge, Button, MicroLabel, StatusBadge, cn } from '../../ui';
import SlaBadge from './SlaBadge';
import { SEVERITY_STRIPE } from '../../lib/eventLabels';
import { relativeTime } from '../../lib/uzDate';
import type { AIEvent } from '../../types';

/** Kamera nomi — hodisada NUSXA qilib saqlanadi (app/services/event_bus.py),
 *  shuning uchun kamera keyinchalik o'chirilsa ham nom qoladi. Lekin juda
 *  eski yozuvlarda (yoki nomsiz import qilingan kamerada) u bo'sh bo'lishi
 *  mumkin: ilgari bunday hodisa qatorida shunchaki BO'SH joy ko'rinardi va
 *  operator hodisa qayerda bo'lganini umuman bilolmasdi. */
export function cameraLabel(event: Pick<AIEvent, 'cameraName' | 'cameraId'>): string {
  if (event.cameraName?.trim()) return event.cameraName;
  return event.cameraId ? "Kamera o'chirilgan" : "Kamera noma'lum";
}

type Decision = 'tasdiqlangan' | 'rad_etilgan';

/** Hodisa kadri (kichik). Kadr saqlanmagan — yoki YUKLANMAGAN bo'lsa
 *  (havola muddati tugagan, saqlash xizmati ishlamayapti) — joy egallovchi.
 *
 *  Ilgari faqat `snapshotUrl` bor-yo'qligi tekshirilardi: havola bor,
 *  lekin rasm ochilmasa (MinIO o'chgan, presigned havola eskirgan)
 *  brauzerning sinib qolgan rasm belgisi ko'rinardi — operator buni
 *  "kadr yo'q" deb emas, "dastur buzuq" deb o'qirdi. */
export function EventThumb({ event, className }: { event: AIEvent; className: string }) {
  const [failed, setFailed] = useState(false);
  // Boshqa hodisaga o'tilganda eski xato qolib ketmasin.
  useEffect(() => setFailed(false), [event.snapshotUrl]);

  if (!event.snapshotUrl || failed) {
    return (
      <div
        className={cn(className, 'flex items-center justify-center bg-surface-2 text-subtle')}
        title={failed ? "Kadrni yuklab bo'lmadi" : 'Kadr saqlanmagan'}
      >
        <ImageOff size={16} aria-hidden="true" />
        <span className="sr-only">{failed ? "Kadrni yuklab bo'lmadi" : 'Kadr saqlanmagan'}</span>
      </div>
    );
  }
  return <img src={event.snapshotUrl} alt="" loading="lazy" onError={() => setFailed(true)} className={cn(className, 'object-cover')} />;
}

/** Navbat / sinov kartasi: kadr, nima va qayerda, SLA, ikki qaror tugmasi. */
export default function ReviewCard({
  event,
  busy,
  onOpen,
  onReview,
}: {
  event: AIEvent;
  busy: boolean;
  onOpen: () => void;
  onReview: (decision: Decision) => void;
}) {
  return (
    <article className="flex flex-col overflow-hidden border border-border bg-surface">
      <div className={cn('h-1', SEVERITY_STRIPE[event.severity])} aria-hidden="true" />
      <button
        type="button"
        onClick={onOpen}
        className="relative block text-left focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-primary/50"
        aria-label={`${event.moduleName} tafsilotlari`}
      >
        <EventThumb event={event} className="aspect-video w-full" />
        <span className="absolute left-2 top-2 flex gap-1">
          <StatusBadge kind="severity" status={event.severity} />
          {event.isTrial && (
            <Badge tone="warning" icon={FlaskConical}>
              Sinov
            </Badge>
          )}
        </span>
        <span className="intel-code absolute bottom-1.5 right-1.5 bg-black/70 px-1.5 py-0.5 text-[11px] text-white" title={event.timestamp}>
          {event.occurredAt ? relativeTime(event.occurredAt) : event.timestamp}
        </span>
      </button>
      <div className="flex flex-1 flex-col px-3 py-2.5">
        <p className="flex items-center gap-2">
          <MicroLabel className="ms-auto">Ishonch {event.confidence}%</MicroLabel>
        </p>
        <p className="mt-0.5 font-semibold text-fg">{event.moduleName}</p>
        {event.personName && <p className="text-[13px] text-fg">{event.personName}</p>}
        <p className="text-xs text-muted">
          {cameraLabel(event)}
          {event.building ? ` · ${event.building}` : ''}
        </p>
        {event.details?.reason && (
          <p className="mt-1.5 line-clamp-2 text-xs text-muted" title={event.details.reason}>
            {event.details.reason}
          </p>
        )}
        {!event.isTrial && (event.status === 'jarayonda' || event.dueAt || event.assignedToName) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {event.status === 'jarayonda' && <StatusBadge kind="event" status="jarayonda" />}
            <SlaBadge event={event} />
            {event.assignedToName && (
              <span className="inline-flex items-center gap-1 text-xs text-muted">
                <UserCheck size={12} aria-hidden="true" />
                {event.assignedToName}
              </span>
            )}
          </div>
        )}
        <div className="mt-auto grid grid-cols-2 gap-1.5 pt-3">
          <Button icon={X} onClick={() => onReview('rad_etilgan')} disabled={busy}>
            Rad etish
          </Button>
          <Button variant="primary" icon={Check} onClick={() => onReview('tasdiqlangan')} disabled={busy}>
            Tasdiqlash
          </Button>
        </div>
      </div>
    </article>
  );
}
