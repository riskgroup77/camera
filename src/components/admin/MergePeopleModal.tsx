import { useEffect, useState } from 'react';
import { ArrowDown, Combine, ScanFace } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState, Modal, SearchInput, Skeleton, cn, useToast } from '../../ui';
import { ApiError } from '../../lib/apiClient';
import { getMergeCandidates, mergeTwo, type MergeCard, type MergePlan } from '../../lib/mergeApi';

/**
 * Qo'lda birlashtirish: bir odamning ikki yozuvi — biri yuz va JSHSHIR bilan,
 * ikkinchisi dars jadvali, guruh va davomat bilan (familiya o'zgargan, harf
 * xatosi, kirill/lotin, faol bo'lmagan klon). Natija — bitta to'liq yozuv,
 * odam yuzini qayta topshirmaydi.
 *
 * Oqim: nomzodni tanlash -> server natijani OLDINDAN ko'rsatadi (bazaga
 * yozmaydi) -> "Birlashtirish". Ikki xil JSHSHIR, boshqa-boshqa yuz yoki
 * talaba/xodim juftligini server rad etadi (xabari shu yerda chiqadi).
 */

const STATUS_LABEL: Record<MergeCard['biometricsStatus'], string> = {
  tasdiqlangan: 'Yuz tasdiqlangan',
  kutilmoqda: 'Yuz kutilmoqda',
  yoq: 'Yuzsiz',
};

function Facts({ card }: { card: MergeCard }) {
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {!card.active && <Badge tone="warning">Faol emas</Badge>}
      <Badge tone={card.biometricsStatus === 'tasdiqlangan' ? 'success' : 'neutral'}>
        {STATUS_LABEL[card.biometricsStatus]}
        {card.biometricsStatus !== 'yoq' && !card.allAngles ? ' (1 tomon)' : ''}
      </Badge>
      {card.hasPinfl && <Badge tone="neutral">JSHSHIR</Badge>}
      {card.hemisLinked && <Badge tone="neutral">HEMIS</Badge>}
      {card.selfRegistered && <Badge tone="neutral">Havola orqali</Badge>}
      {card.attendance > 0 && <Badge tone="neutral">{card.attendance} kun davomat</Badge>}
      {card.lessons > 0 && <Badge tone="neutral">{card.lessons} dars</Badge>}
    </div>
  );
}

function CardRow({ card, tone, onClick, selected }: { card: MergeCard; tone?: 'keep' | 'remove'; onClick?: () => void; selected?: boolean }) {
  const body = (
    <>
      {card.photoUrl ? (
        <img src={card.photoUrl} alt="" loading="lazy" className="h-12 w-12 shrink-0 rounded-control object-cover" />
      ) : (
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-control bg-surface-2 text-[10px] text-subtle">yuzsiz</span>
      )}
      <div className="min-w-0 flex-1 text-left">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-bold">{card.fullName}</span>
          {card.biometricsStatus === 'tasdiqlangan' && <ScanFace size={13} className="shrink-0 text-success" aria-label="Yuzi bor" />}
        </div>
        <div className="truncate text-[11px] text-muted">
          {[card.groupOrPosition, card.faculty, card.createdAt ? `qo‘shilgan ${card.createdAt}` : null].filter(Boolean).join(' · ')}
        </div>
        <Facts card={card} />
      </div>
    </>
  );
  const cls = cn(
    'flex w-full min-w-0 items-start gap-2.5 rounded-control border px-2.5 py-2',
    tone === 'keep' && 'border-success/40 bg-success-soft',
    tone === 'remove' && 'border-danger/40 bg-danger-soft',
    !tone && 'border-border',
    selected && 'border-primary ring-1 ring-primary',
  );
  return onClick ? (
    <button type="button" onClick={onClick} className={cn(cls, 'hover:border-primary/60')}>
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export default function MergePeopleModal({
  person,
  initialSearch = '',
  onClose,
  onMerged,
}: {
  /** Shu odam bilan birlashtiriladi; null — oyna yopiq. */
  person: { id: string; fullName: string } | null;
  /** Masalan, tahrirlashdagi "JSHSHIR boshqa yozuvda" — o'sha JSHSHIR. */
  initialSearch?: string;
  onClose: () => void;
  onMerged: (plan: MergePlan) => void;
}) {
  const toast = useToast();
  const [search, setSearch] = useState(initialSearch);
  const [candidates, setCandidates] = useState<MergeCard[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MergeCard | null>(null);
  const [plan, setPlan] = useState<MergePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);

  useEffect(() => {
    if (!person) return;
    setSearch(initialSearch);
    setSelected(null);
    setPlan(null);
    setPlanError(null);
  }, [person, initialSearch]);

  useEffect(() => {
    if (!person) return;
    const controller = new AbortController();
    setCandidates(null);
    setListError(null);
    const timer = window.setTimeout(() => {
      getMergeCandidates(person.id, search, controller.signal)
        .then(setCandidates)
        .catch((err) => {
          if (!controller.signal.aborted) setListError(err instanceof ApiError ? err.message : 'Ro‘yxatni olib bo‘lmadi');
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [person, search]);

  useEffect(() => {
    if (!person || !selected) return;
    let stale = false;
    setPlan(null);
    setPlanError(null);
    mergeTwo(person.id, selected.id, false)
      .then((result) => !stale && setPlan(result))
      .catch((err) => !stale && setPlanError(err instanceof ApiError ? err.message : 'Natijani hisoblab bo‘lmadi'));
    return () => {
      stale = true;
    };
  }, [person, selected]);

  async function apply() {
    if (!person || !selected) return;
    setMerging(true);
    try {
      const result = await mergeTwo(person.id, selected.id, true);
      toast.success(`Birlashtirildi: ${result.result.fullName}`);
      onMerged(result);
      onClose();
    } catch (err) {
      setPlanError(err instanceof ApiError ? err.message : 'Birlashtirib bo‘lmadi');
    } finally {
      setMerging(false);
    }
  }

  return (
    <Modal
      open={!!person}
      onClose={onClose}
      size="lg"
      dismissible={!merging}
      title="Birlashtirish"
      description={person ? `${person.fullName} — bir odamning ikkinchi yozuvini tanlang` : undefined}
      footer={
        <>
          <Button onClick={onClose} disabled={merging}>
            Bekor qilish
          </Button>
          <Button variant="primary" icon={Combine} disabled={!plan} loading={merging} onClick={apply}>
            Birlashtirish
          </Button>
        </>
      }
    >
      {!selected ? (
        <div className="flex flex-col gap-3">
          <SearchInput value={search} onChange={setSearch} placeholder="F.I.Sh. yoki JSHSHIR" size="sm" autoFocus />
          <p className="text-[12px] text-muted">
            {search.trim()
              ? 'Faol bo‘lmagan yozuvlar ham qidiriladi.'
              : 'Ism va otasining ismi mos yozuvlar (familiya o‘zgargan bo‘lsa ham). Topilmasa — F.I.Sh. yoki JSHSHIR yozing.'}
          </p>
          {listError ? (
            <ErrorState message={listError} />
          ) : !candidates ? (
            <div className="space-y-2">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : candidates.length === 0 ? (
            <EmptyState title="Mos yozuv topilmadi" description="F.I.Sh. yoki JSHSHIR bilan qidirib ko‘ring" compact />
          ) : (
            <ul className="max-h-[50vh] space-y-1.5 overflow-y-auto pr-1">
              {candidates.map((card) => (
                <li key={card.id}>
                  <CardRow card={card} onClick={() => setSelected(card)} />
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          <button type="button" onClick={() => setSelected(null)} className="self-start text-[12px] font-semibold text-primary hover:underline">
            ← Boshqa yozuvni tanlash
          </button>
          {planError ? (
            <ErrorState title="Birlashtirib bo‘lmaydi" message={planError} />
          ) : !plan ? (
            <Skeleton className="h-40" />
          ) : (
            <>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-success">Qoladi (yuzi shu yozuvda)</p>
              <CardRow card={plan.keep} tone="keep" />
              <p className="text-[11px] font-semibold uppercase tracking-wide text-danger">Ma’lumoti ko‘chib, o‘chiriladi</p>
              <CardRow card={plan.remove} tone="remove" />
              <div className="flex justify-center text-muted">
                <ArrowDown size={18} aria-hidden="true" />
              </div>
              <div className="rounded-control border border-primary/40 bg-primary-soft px-3 py-2.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">Natija — bitta yozuv</p>
                <p className="mt-0.5 text-[14px] font-bold">{plan.result.fullName}</p>
                <p className="text-[12px] text-muted">{[plan.result.groupOrPosition, plan.result.faculty].filter(Boolean).join(' · ')}</p>
                <ul className="mt-1.5 space-y-0.5 text-[12px]">
                  <li>{plan.result.active ? '✅ Faol — reestrda va hisobotlarda ko‘rinadi' : '⚠️ Faol emas'}</li>
                  <li>
                    {plan.result.biometricsStatus === 'tasdiqlangan'
                      ? `✅ Yuz tasdiqlangan${plan.result.allAngles ? ' (3 tomonlama)' : ''} — kamera taniydi`
                      : '⚠️ Yuz tasdiqlanmagan — havola orqali o‘tishi kerak'}
                  </li>
                  <li>{plan.result.hasPinfl ? '✅ JSHSHIR bor' : '— JSHSHIR yo‘q'}</li>
                  {plan.result.hemisLinked && <li>✅ HEMIS bilan bog‘langan (dars jadvali shu yozuvda)</li>}
                  {plan.result.attendance > 0 && <li>✅ {plan.result.attendance} kunlik davomat saqlanadi</li>}
                </ul>
              </div>
              <p className="text-[11px] text-muted">Odam yuzini qayta topshirmaydi. Amal audit jurnaliga yoziladi.</p>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
