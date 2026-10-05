import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Copy, ExternalLink, Printer, UserRoundX, Users } from 'lucide-react';
import { Avatar, Badge, Button, ButtonLink, Drawer, EmptyState, ErrorState, ProgressBar, Skeleton, cn, focusRing, formatNumber, formatPercent, useToast } from '../../ui';
import { getEnrollmentMissing, situationPaths, type EnrollMissing } from '../../lib/situationApi';
import { enrollTone } from '../../lib/studentAttendance';
import { EnrollPrintPortal, EnrollQrCard } from './EnrollQrCard';
import { useAsyncData } from './useAsyncData';

export interface EnrollDrawerTarget {
  name: string;
  faculty?: string | null;
}

/** "Topshirmaganlar" paneli: guruhning yuzi yo'q talabalari + chop etiladigan QR karta. */
export function GroupEnrollDrawer({ target, onClose, withDate }: { target: EnrollDrawerTarget | null; onClose: () => void; withDate: (path: string) => string }) {
  const name = target?.name ?? null;
  const res = useAsyncData<EnrollMissing>(name ? `miss|${name}` : null, (signal) => getEnrollmentMissing(name!, { signal }), { identity: name ?? '' });
  const data = res.data;
  const [printing, setPrinting] = useState(false);
  const toast = useToast();
  const donePrint = useCallback(() => setPrinting(false), []);
  const faculty = target?.faculty ?? null;

  const enrollUrl = data?.enrollUrl ?? '';

  const printCards = useMemo(
    () => (printing && data ? [{ group: data.group, url: enrollUrl, faculty }] : null),
    [printing, data, enrollUrl, faculty],
  );

  const confirmed = data ? data.total - data.missing.length : 0;
  const pct = data && data.total ? Math.round((confirmed / data.total) * 1000) / 10 : null;

  async function copy() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(enrollUrl);
      toast.success('Havola nusxalandi');
    } catch {
      toast.error("Nusxalab bo'lmadi");
    }
  }


  return (
    <>
    <Drawer
      open={target !== null}
      onClose={onClose}
      size="lg"
      title={name ? `${name} — yuz topshirish` : ''}
      subtitle={target?.faculty ?? undefined}
      actions={name ? <ButtonLink to={withDate(situationPaths.group(name))} size="sm" variant="ghost" icon={ExternalLink}>Guruh</ButtonLink> : undefined}
      footer={
        data ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={Printer} onClick={() => setPrinting(true)}>
              Chop etish
            </Button>
            <Button icon={Copy} onClick={copy}>
              Havolani nusxalash
            </Button>
          </div>
        ) : undefined
      }
    >
      {res.loading ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-96" />
        </div>
      ) : res.error && !data ? (
        <ErrorState message={res.error} onRetry={res.reload} />
      ) : data ? (
        <div className="flex flex-col gap-6">
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm text-muted">
                <span className="text-2xl font-semibold tabular-nums text-fg">{formatNumber(confirmed)}</span> / {formatNumber(data.total)} talaba yuz topshirgan
              </p>
              <span className="text-lg font-semibold tabular-nums text-fg">{formatPercent(pct)}</span>
            </div>
            <ProgressBar value={pct} tone={enrollTone(pct)} size="md" className="mt-2" ariaLabel="Yuz topshirish progressi" />
          </div>

          <section className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
            <div className="min-w-0">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
                <UserRoundX size={16} className="text-muted" aria-hidden="true" />
                Topshirmaganlar
                <Badge tone={data.missing.length ? 'warning' : 'success'}>{data.missing.length}</Badge>
              </h3>
              {data.missing.length === 0 ? (
                <EmptyState compact icon={Users} title="Hamma topshirgan" description="Bu guruhda davomat avtomatik yuritiladi." />
              ) : (
                <ul className="flex max-h-[28rem] flex-col divide-y divide-border overflow-y-auto rounded-control border border-border">
                  {data.missing.map((s) => (
                    <li key={s.id}>
                      <Link to={withDate(situationPaths.person(s.id))} className={cn('flex items-center gap-3 px-3 py-2 text-sm hover:bg-surface-2', focusRing)}>
                        <Avatar name={s.fullName} size="sm" />
                        <span className="min-w-0 flex-1 truncate text-fg">{s.fullName}</span>
                        <Badge tone={s.biometricsStatus === 'kutilmoqda' ? 'info' : 'neutral'} size="sm">
                          {s.biometricsStatus === 'kutilmoqda' ? 'Tasdiq kutilmoqda' : "Yuz yo'q"}
                        </Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="mt-3 text-sm font-semibold text-fg">Guruh uchun QR karta</h3>
              <p className="text-xs text-muted">Chop etib, guruh xonasiga yoki sardorga bering — talabalar telefonidan o&apos;zi topshiradi.</p>
              <EnrollQrCard
                group={data.group}
                url={enrollUrl}
                faculty={target?.faculty}
                missing={data.missing.length}
                className="p-4 [&_.enroll-card-group]:text-2xl [&_ol]:text-xs"
              />
            </div>
          </section>
        </div>
      ) : null}
      <EnrollPrintPortal cards={printCards} onDone={donePrint} />
    </Drawer>
    </>
  );
}
