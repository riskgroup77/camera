import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Copy, Printer, UserRoundX, Users } from 'lucide-react';
import { Avatar, Badge, Button, Drawer, EmptyState, ProgressBar, cn, focusRing, formatNumber, formatPercent, useToast } from '../../ui';
import { situationPaths, type KafedraDetail } from '../../lib/situationApi';
import { enrollTone } from '../../lib/studentAttendance';
import { EnrollPrintPortal, EnrollQrCard } from '../students/EnrollQrCard';

/** Bo'linma (kafedra, bo'lim) xodimlarining yuz topshirishi: kim hali
 *  topshirmagan va chop etiladigan QR karta. Ma'lumot kafedra sahifasining
 *  o'zidan — qo'shimcha so'rovsiz. */
export function UnitEnrollDrawer({
  unit,
  open,
  onClose,
  withDate,
}: {
  unit: KafedraDetail | null;
  open: boolean;
  onClose: () => void;
  withDate: (path: string) => string;
}) {
  const toast = useToast();
  const [printing, setPrinting] = useState(false);
  const donePrint = useCallback(() => setPrinting(false), []);
  const url = `${window.location.origin}/royxatdan-otish`;
  const missing = useMemo(() => (unit?.teachers ?? []).filter((t) => t.biometricsStatus !== 'tasdiqlangan'), [unit]);
  const total = unit?.teachers.length ?? 0;
  const confirmed = total - missing.length;
  const pct = total ? Math.round((confirmed / total) * 1000) / 10 : null;
  const printCards = useMemo(() => (printing && unit ? [{ group: unit.name, url }] : null), [printing, unit, url]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      toast.success('Havola nusxalandi');
    } catch {
      toast.error("Nusxalab bo'lmadi");
    }
  }

  return (
    <Drawer
      open={open && unit !== null}
      onClose={onClose}
      size="lg"
      title={unit ? `${unit.name} — yuz topshirish` : ''}
      footer={
        unit ? (
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
      {unit && (
        <div className="flex flex-col gap-6">
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm text-muted">
                <span className="text-2xl font-semibold tabular-nums text-fg">{formatNumber(confirmed)}</span> / {formatNumber(total)} xodim yuz topshirgan
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
                <Badge tone={missing.length ? 'warning' : 'success'}>{missing.length}</Badge>
              </h3>
              {missing.length === 0 ? (
                <EmptyState compact icon={Users} title="Hamma topshirgan" description="Bu bo'linmada davomat avtomatik yuritiladi." />
              ) : (
                <ul className="flex max-h-[28rem] flex-col divide-y divide-border overflow-y-auto rounded-control border border-border">
                  {missing.map((t) => (
                    <li key={t.id}>
                      <Link to={withDate(situationPaths.person(t.id))} className={cn('flex items-center gap-3 px-3 py-2 text-sm hover:bg-surface-2', focusRing)}>
                        <Avatar name={t.fullName} size="sm" />
                        <span className="min-w-0 flex-1 truncate text-fg">{t.fullName}</span>
                        <Badge tone={t.biometricsStatus === 'kutilmoqda' ? 'info' : 'neutral'} size="sm">
                          {t.biometricsStatus === 'kutilmoqda' ? 'Tasdiq kutilmoqda' : "Yuz yo'q"}
                        </Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="mt-3 text-sm font-semibold text-fg">Bo‘linma uchun QR karta</h3>
              <p className="text-xs text-muted">Chop etib, bo‘linma xonasiga iling — xodimlar telefonidan o‘zi topshiradi.</p>
              <EnrollQrCard group={unit.name} url={url} missing={missing.length} className="p-4 [&_.enroll-card-group]:text-xl [&_ol]:text-xs" />
            </div>
          </section>
        </div>
      )}
      <EnrollPrintPortal cards={printCards} onDone={donePrint} />
    </Drawer>
  );
}
