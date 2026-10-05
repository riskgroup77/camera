import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, RefreshCw, UserCheck, X } from 'lucide-react';
import { ApiError, isAbortError } from '../../lib/apiClient';
import { isBackendConfigured } from '../../lib/config';
import { sightingTime } from '../../lib/notanishlarApi';
import {
  accuracyPath,
  confirmReview,
  getReviewQueue,
  indexAfterRemoval,
  percent,
  precisionRag,
  rejectReview,
  reviewKeyAction,
  type Accuracy,
  type ModuleAccuracy,
  type ReviewItem,
} from '../../lib/tekshiruvApi';
import { useApiResource } from '../../lib/useApiResource';
import { addDays, todayInTashkent } from '../../lib/uzDate';
import RecurringUnknowns from '../../components/review/RecurringUnknowns';
import {
  Button,
  Card,
  DataTable,
  DatePicker,
  EmptyState,
  ErrorState,
  Page,
  SkeletonCards,
  SkeletonTiles,
  StatTile,
  cn,
  rag,
  useToast,
  useUrlTab,
  type DataTableColumn,
  type TabItem,
} from '../../ui';

/**
 * Yuz tekshiruvi — "kulrang zona" mosliklari va o'lchangan aniqlik.
 *
 * Kuchsiz CPU va CCTV burchagida haqiqiy moslik ko'pincha 0.42-0.50 da
 * qoladi (qat'iy chegara 0.50). Bunday yuz shu yerda kamera kadri va
 * ro'yxat rasmi yonma-yon turadi: "Ha, u" davomat yozadi va yuzni
 * galereyaga qo'shadi — tizim o'sha odamni keyingi safar o'zi taniydi.
 */

type TabId = 'navbat' | 'takroriy' | 'aniqlik';

const DAYS = 30;

export default function ReviewPage() {
  const [pending, setPending] = useState<number | null>(null);
  const [recurring, setRecurring] = useState<number | null>(null);
  const tabs: TabItem<TabId>[] = [
    { id: 'navbat', label: 'Navbat', count: pending },
    { id: 'takroriy', label: 'Takroriy yuzlar', count: recurring },
    { id: 'aniqlik', label: 'Aniqlik' },
  ];
  const [tab] = useUrlTab(tabs, { defaultTab: 'navbat' });

  return (
    <Page title="Tekshiruv" breadcrumbs={[{ label: 'Monitoring' }, { label: 'Tekshiruv' }]} tabs={tabs} defaultTab="navbat">
      {tab === 'navbat' ? (
        <QueueTab onPending={setPending} />
      ) : tab === 'takroriy' ? (
        <RecurringUnknowns onPending={setRecurring} />
      ) : (
        <AccuracyTab />
      )}
    </Page>
  );
}

// ─────────────────────────────────────────────── Navbat

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

function QueueTab({ onPending }: { onPending: (n: number | null) => void }) {
  const toast = useToast();
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);
  const [version, setVersion] = useState(0);
  // Navbat bir kunlik: kechagi hal qilinmagan yuzlar ham ko'rib chiqilishi mumkin.
  const today = todayInTashkent();
  const [day, setDay] = useState(today);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());

  const resolvedIds = useRef(new Set<string>());
  useEffect(() => {
    if (!isBackendConfigured) return;
    const controller = new AbortController();
    setItems(null);
    getReviewQueue({ sana: day, holat: 'kutilmoqda', limit: 100 }, { signal: controller.signal })
      .then((res) => {
        // Hal qilingan (yoki so'rovi hali yo'lda) kartalar qayta chiqmasin:
        // oxirgi karta hal qilinganda navbat darhol qayta so'raladi, server
        // esa hali POST'ni qayta ishlamagan bo'lishi mumkin.
        const done = resolvedIds.current;
        setItems(res.items.filter((row) => !done.has(row.id)));
        setPending(res.pending);
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : 'Navbat olinmadi');
      });
    return () => controller.abort();
  }, [version, day]);

  useEffect(() => onPending(day === today ? pending : null), [pending, onPending, day, today]);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  const resolve = useCallback(
    (item: ReviewItem, action: 'confirm' | 'reject') => {
      // Optimistik: kartani darhol olib tashlaymiz — operator keyingisiga
      // o'tadi. Xato bo'lsa karta o'z joyiga qaytadi.
      let position = 0;
      setItems((prev) => {
        if (!prev) return prev;
        position = prev.findIndex((row) => row.id === item.id);
        const next = prev.filter((row) => row.id !== item.id);
        setSelected((index) => indexAfterRemoval(index, next.length));
        return next;
      });
      setPending((n) => (n === null ? n : Math.max(0, n - 1)));
      resolvedIds.current.add(item.id);
      (action === 'confirm' ? confirmReview(item.id) : rejectReview(item.id)).then((res) => {
        if (action === 'confirm' && res?.message) toast.success(res.message);
      }).catch((err) => {
        resolvedIds.current.delete(item.id);
        setItems((prev) => {
          if (!prev) return prev;
          const next = [...prev];
          next.splice(Math.max(0, position), 0, item);
          return next;
        });
        setPending((n) => (n === null ? n : n + 1));
        toast.error(err instanceof ApiError ? err.message : 'Saqlanmadi');
      });
    },
    [toast],
  );

  // Ekrandagi kartalar tugasa, lekin navbatda yana bor — keyingi qismini olamiz.
  useEffect(() => {
    if (items && items.length === 0 && pending !== null && pending > 0) reload();
  }, [items, pending, reload]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event.target) || !items || items.length === 0) return;
      const action = reviewKeyAction(event);
      if (!action) return;
      event.preventDefault();
      const current = items[Math.min(selected, items.length - 1)];
      if (action === 'confirm' || action === 'reject') resolve(current, action);
      else if (action === 'next') setSelected((i) => Math.min(items.length - 1, i + 1));
      else setSelected((i) => Math.max(0, i - 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [items, selected, resolve]);

  const selectedId = items?.[selected]?.id;
  useEffect(() => {
    if (selectedId) cardRefs.current.get(selectedId)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [selectedId]);

  const dayBar = (
    <div className="flex flex-wrap items-center gap-2">
      <DatePicker value={day} onChange={(value) => setDay(value || today)} max={today} size="sm" />
      {day === today ? (
        <Button size="sm" variant="ghost" onClick={() => setDay(addDays(today, -1))}>
          Kechagi qolganlar
        </Button>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setDay(today)}>
          Bugunga qaytish
        </Button>
      )}
    </div>
  );

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (items === null) return <>{dayBar}<SkeletonCards /></>;
  if (items.length === 0) {
    return (
      <>
        {dayBar}
        <EmptyState
          icon={UserCheck}
          tone="success"
          title="Navbat bo‘sh"
          description="Bu kun uchun tekshiriladigan yuz yo‘q. Bu yerga kamera odamni «ehtimol shu» deb topgan, lekin davomat yozishga yetarli ishonch bo‘lmagan yuzlar tushadi — siz «Ha, u» desangiz davomat yoziladi va tanish aniqlashadi. Bazada umuman yo‘q, lekin tez-tez ko‘rinadigan yuzlar «Takroriy yuzlar» bo‘limida."
        />
      </>
    );
  }

  return (
    <>
      {dayBar}
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted">
        <span>
          <b className="text-fg tabular-nums">{pending ?? items.length}</b> ta kutilmoqda ·{' '}
          <kbd className="rounded border border-border px-1 font-mono">T</kbd> ha ·{' '}
          <kbd className="rounded border border-border px-1 font-mono">R</kbd> yo‘q ·{' '}
          <kbd className="rounded border border-border px-1 font-mono">←→</kbd> yurish
        </span>
        <Button size="sm" variant="ghost" icon={RefreshCw} onClick={reload}>
          Yangilash
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item, index) => (
          <ReviewCard
            key={item.id}
            item={item}
            active={index === selected}
            onSelect={() => setSelected(index)}
            onResolve={resolve}
            refCallback={(el) => {
              if (el) cardRefs.current.set(item.id, el);
              else cardRefs.current.delete(item.id);
            }}
          />
        ))}
      </div>
    </>
  );
}

function FaceImage({ url, label }: { url: string | null; label: string }) {
  return (
    <figure className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="aspect-square overflow-hidden rounded-control bg-surface-2">
        {url ? (
          <img src={url} alt={label} loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] text-subtle">Rasm yo‘q</div>
        )}
      </div>
      <figcaption className="text-center text-[11px] text-subtle">{label}</figcaption>
    </figure>
  );
}

function ReviewCard({
  item,
  active,
  onSelect,
  onResolve,
  refCallback,
}: {
  item: ReviewItem;
  active: boolean;
  onSelect: () => void;
  onResolve: (item: ReviewItem, action: 'confirm' | 'reject') => void;
  refCallback: (el: HTMLElement | null) => void;
}) {
  return (
    <div ref={refCallback}>
      <Card
        padding="sm"
        onClick={onSelect}
        aria-current={active ? 'true' : undefined}
        className={cn('flex flex-col gap-2.5 transition', active && 'ring-2 ring-primary/50')}
      >
        <div className="flex gap-2">
          <FaceImage url={item.cropUrl} label="Kamera" />
          <FaceImage url={item.photoUrl} label="Ro‘yxat" />
        </div>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold text-fg">{item.personName}</div>
            <div className="truncate text-[12px] text-muted">{item.group}</div>
          </div>
          <span
            className="shrink-0 rounded-full bg-warning-soft px-2 py-0.5 text-[12px] font-bold tabular-nums text-warning"
            title="O‘xshashlik"
          >
            {percent(item.similarity)}
          </span>
        </div>
        <div className="truncate text-[12px] text-subtle">
          {item.cameraName ?? 'Kamera'} · {sightingTime(item.firstSeenAt)}
          {item.hits > 1 && ` · ${item.hits} marta`}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Button
            variant="primary"
            icon={Check}
            onClick={(event) => {
              event.stopPropagation();
              onResolve(item, 'confirm');
            }}
            title="T"
          >
            Ha, u
          </Button>
          <Button
            icon={X}
            onClick={(event) => {
              event.stopPropagation();
              onResolve(item, 'reject');
            }}
            title="R"
          >
            Yo‘q
          </Button>
        </div>
      </Card>
    </div>
  );
}

// ─────────────────────────────────────────────── Aniqlik

const MODULE_COLUMNS: DataTableColumn<ModuleAccuracy>[] = [
  { key: 'name', header: 'Modul', cell: (row) => <span className="text-fg">{row.name}</span> },
  { key: 'confirmed', header: 'Tasdiqlangan', align: 'right', sortValue: (row) => row.confirmed, sortFirst: 'desc' },
  { key: 'rejected', header: 'Rad etilgan', align: 'right', sortValue: (row) => row.rejected, sortFirst: 'desc' },
  { key: 'pending', header: 'Kutilmoqda', align: 'right', hideOnMobile: true },
  {
    key: 'precision',
    header: 'Aniqlik',
    align: 'right',
    sortValue: (row) => row.precision,
    sortFirst: 'desc',
    cell: (row) => percent(row.precision),
  },
];

function AccuracyTab() {
  const { data, loading, error, reload } = useApiResource<Accuracy>(accuracyPath(DAYS));

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !data) return <SkeletonTiles />;
  if (!data) return null;

  const queueDecided = data.queue.confirmed + data.queue.rejected;
  const pct = (ratio: number | null) => (ratio === null ? null : Math.round(ratio * 100));

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Navbat: “ha”"
          value={percent(data.queue.confirmRate)}
          hint={`${data.queue.confirmed} / ${queueDecided} · ${DAYS} kun`}
        />
        <StatTile
          label="Talabalar yuzi"
          value={percent(data.students.ratio)}
          hint={`${data.students.enrolled} / ${data.students.total}`}
          progress={pct(data.students.ratio)}
          rag={rag(pct(data.students.ratio))}
        />
        <StatTile
          label="Xodimlar yuzi"
          value={percent(data.staff.ratio)}
          hint={`${data.staff.enrolled} / ${data.staff.total}`}
          progress={pct(data.staff.ratio)}
          rag={rag(pct(data.staff.ratio))}
        />
        <StatTile
          label="Bugun tanildi"
          value={data.recognizedToday}
          hint={`${percent(data.enrolledTodayRatio)} yuzi borlardan`}
          progress={pct(data.enrolledTodayRatio)}
        />
      </div>
      <DataTable
        columns={MODULE_COLUMNS}
        rows={data.modules}
        rowKey={(row) => String(row.code)}
        rowRag={precisionRag}
        ragHeader="Holat"
        defaultSort={{ key: 'precision', dir: 'asc' }}
        emptyTitle="Qaror yo‘q"
        emptyDescription={`So‘nggi ${DAYS} kunda hodisa tasdiqlanmagan ham, rad etilmagan ham.`}
        ariaLabel="Modullar aniqligi"
      />
    </>
  );
}
