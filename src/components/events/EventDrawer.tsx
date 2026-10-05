import { useEffect, useRef, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, ExternalLink, FlaskConical, ImageOff, Lightbulb, MonitorPlay, Trash2, X } from 'lucide-react';
import { Badge, Button, ButtonLink, Drawer, IconButton, KeyValue, StatusBadge, topDialogPanel, type KeyValueItem } from '../../ui';
import EventActivity from './EventActivity';
import { cameraLabel } from './ReviewCard';
import EventWorkflowPanel from './EventWorkflowPanel';
import EventSopChecklist from './EventSopChecklist';
import { detailMetrics } from '../../lib/eventDetails';
import { relativeTime } from '../../lib/uzDate';
import type { AIEvent } from '../../types';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';

type Decision = 'tasdiqlangan' | 'rad_etilgan';

function Kbd({ children }: { children: string }) {
  return <kbd className="ml-0.5 hidden rounded border border-current px-1 text-[10px] font-medium leading-4 opacity-60 sm:inline">{children}</kbd>;
}

/** Hodisa tafsiloti — ro'yxatdan chiqmasdan, klaviatura bilan tez ko'rib chiqish:
 *  T — tasdiqlash, R — rad etish, ← → — oldingi/keyingi hodisa.
 *  Ish jarayoni (mas'ul, muddat, holat, yechim) va tarix/izohlar ham shu yerda;
 *  `onChanged` berilmasa (masalan faqat ko'rish rejimi) ular ko'rsatilmaydi. */
export default function EventDrawer({
  event,
  onClose,
  onReview,
  onChanged,
  onDelete,
  onPrev,
  onNext,
  position,
  busy = false,
}: {
  event: AIEvent | null;
  onClose: () => void;
  onReview: (event: AIEvent, status: Decision) => void;
  onChanged?: (updated: AIEvent) => void;
  onDelete?: (event: AIEvent) => void;
  onPrev?: () => void;
  onNext?: () => void;
  position?: string;
  busy?: boolean;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const [snapshotFailed, setSnapshotFailed] = useState(false);
  const { role } = useAuth();
  const { can } = usePermissions();
  const canLive = can('viewLive', role);
  // Boshqa hodisaga o'tilganda oldingi kadrning xatosi qolib ketmasin.
  useEffect(() => setSnapshotFailed(false), [event?.id, event?.snapshotUrl]);

  useEffect(() => {
    if (!event) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // USTIMIZDA BOSHQA DIALOG BORMI. "O'chirish" tasdig'i yoki "Hal
      // qilindi" oynasi ochilganda panelning tezkor tugmalari ishlab
      // ketardi: tasdiq oynasida bosilgan "t" hodisani jimgina
      // tasdiqlab, "r" esa rad etib yuborardi — orqada, foydalanuvchi
      // ko'rmagan holda. Eng ustki dialog biz bo'lmasak — tinch turamiz.
      if (topDialogPanel() !== panelRef.current) return;
      if (e.key === 'ArrowLeft' && onPrev) {
        e.preventDefault();
        onPrev();
      } else if (e.key === 'ArrowRight' && onNext) {
        e.preventDefault();
        onNext();
      } else if (!busy && (e.key === 't' || e.key === 'T') && event.status !== 'tasdiqlangan') {
        onReview(event, 'tasdiqlangan');
      } else if (!busy && (e.key === 'r' || e.key === 'R') && event.status !== 'rad_etilgan') {
        onReview(event, 'rad_etilgan');
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [event, onPrev, onNext, onReview, busy]);

  const metrics = detailMetrics(event?.details);
  const reason = event?.details?.reason;

  const facts: KeyValueItem[] = event
    ? [
        { label: 'Vaqt', value: event.timestamp, hint: event.occurredAt ? relativeTime(event.occurredAt) : undefined },
        { label: 'Kriteriya', value: `№${event.moduleCode} ${event.moduleName}` },
        { label: 'Kamera', value: cameraLabel(event) },
        ...(event.building ? [{ label: 'Bino', value: event.building }] : []),
        ...(event.personName ? [{ label: 'Shaxs', value: event.personName }] : []),
        ...(event.reviewedBy ? [{ label: "Ko'rib chiqdi", value: event.reviewedBy, hint: event.reviewedAt ?? undefined }] : []),
      ]
    : [];

  return (
    <Drawer
      open={!!event}
      onClose={onClose}
      panelRef={panelRef}
      size="lg"
      title={event?.moduleName}
      subtitle={event ? `${cameraLabel(event)}${event.building ? ` · ${event.building}` : ''}` : undefined}
      footer={
        event && (
          <div className="flex w-full flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1">
              <IconButton icon={ChevronLeft} label="Oldingi hodisa" onClick={onPrev} disabled={!onPrev} />
              {position && <span className="px-1 text-xs tabular-nums text-muted">{position}</span>}
              <IconButton icon={ChevronRight} label="Keyingi hodisa" onClick={onNext} disabled={!onNext} />
              {onDelete && <IconButton icon={Trash2} label="Hodisani o'chirish" variant="danger" onClick={() => onDelete(event)} className="ml-1" />}
            </div>
            <div className="flex items-center gap-2">
              <Button icon={X} onClick={() => onReview(event, 'rad_etilgan')} disabled={busy || event.status === 'rad_etilgan'}>
                Rad etish
                <Kbd>R</Kbd>
              </Button>
              <Button variant="primary" icon={Check} onClick={() => onReview(event, 'tasdiqlangan')} disabled={busy || event.status === 'tasdiqlangan'}>
                Tasdiqlash
                <Kbd>T</Kbd>
              </Button>
            </div>
          </div>
        )
      }
    >
      {event && (
        <div className="space-y-4">
          <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-card bg-black">
            {event.snapshotUrl && !snapshotFailed ? (
              <a
                href={event.snapshotUrl}
                target="_blank"
                rel="noreferrer"
                className="group block h-full w-full focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-primary/60"
              >
                <img
                  src={event.snapshotUrl}
                  alt={`${event.moduleName} — ${event.cameraName}`}
                  onError={() => setSnapshotFailed(true)}
                  className="h-full w-full object-contain"
                />
                <span className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-[11px] text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                  <ExternalLink size={12} aria-hidden="true" />
                  To&apos;liq
                </span>
              </a>
            ) : (
              <div className="flex flex-col items-center gap-1.5 text-white/40">
                <ImageOff size={28} aria-hidden="true" />
                <span className="text-xs">{snapshotFailed ? "Kadrni yuklab bo'lmadi" : 'Kadr saqlanmagan'}</span>
                {snapshotFailed && (
                  <a
                    href={event.snapshotUrl ?? '#'}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-white/70 underline focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-primary/60"
                  >
                    Havolani ochish
                  </a>
                )}
              </div>
            )}
          </div>

          {canLive && event.cameraId && (
            <div className="flex flex-wrap gap-2">
              {/* Kadr — bir lahza. Operator vaziyatni hozir ko'rishi kerak. */}
              <ButtonLink to={`/videodevor?kamera=${encodeURIComponent(event.cameraId)}`} icon={MonitorPlay} size="sm">
                Kamerani jonli ko‘rish
              </ButtonLink>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge kind="event" status={event.status} />
            <StatusBadge kind="severity" status={event.severity} />
            <Badge tone="primary">{`Ishonch: ${event.confidence}%`}</Badge>
            {event.isTrial && (
              <Badge tone="warning" icon={FlaskConical}>
                Sinov
              </Badge>
            )}
          </div>

          {/* Ko‘rsatma qaror panelidan OLDIN: operator avval qadamlarni ko‘radi. */}
          {!event.isTrial && event.sop && event.sop.length > 0 && <EventSopChecklist key={event.id} steps={event.sop} />}

          {onChanged && !event.isTrial && <EventWorkflowPanel key={event.id} event={event} onChanged={onChanged} />}

          {(reason || metrics.length > 0) && (
            <section className="rounded-card border border-border bg-surface-2/60 p-3.5">
              <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
                <Lightbulb size={13} aria-hidden="true" className="text-warning" />
                Nega signal?
              </h3>
              {reason && <p className="text-sm leading-relaxed text-fg">{reason}</p>}
              {metrics.length > 0 && (
                <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                  {metrics.map((metric) => (
                    <div key={metric.key} className="flex justify-between gap-2 border-b border-border py-1">
                      <dt className="text-muted">{metric.label}</dt>
                      <dd className="font-medium tabular-nums text-fg">{metric.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
          )}

          <KeyValue items={facts} />

          {onChanged && !event.isTrial && <EventActivity key={event.id} event={event} />}
        </div>
      )}
    </Drawer>
  );
}
