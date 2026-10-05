import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ScanFace } from 'lucide-react';
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, Modal, Skeleton, cn, useToast } from '../../ui';
import { ApiError } from '../../lib/apiClient';
import { getDuplicates, mergeDuplicates, type DuplicateGroup, type DuplicatePerson } from '../../lib/duplicatesApi';

/**
 * Bir odamning bir nechta yozuvi — ko'rib chiqish va birlashtirish.
 *
 * Har guruhda chapdagisi QOLADI (rasmiy import: JSHSHIR bor), o'ngdagilari
 * unga qo'shilib o'chiriladi: yuz, davomat, tashriflar, JSHSHIR va to'liq
 * ism yo'qolmaydi. Adash (otasining ismi yoki JSHSHIR boshqa) bu ro'yxatga
 * umuman tushmaydi. Guruhni belgidan olib, qoldirish mumkin.
 */

function PersonCell({ person, keep }: { person: DuplicatePerson; keep?: boolean }) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2 rounded-control border px-2.5 py-1.5', keep ? 'border-success/40 bg-success-soft' : 'border-border')}>
      {person.photoUrl ? (
        <img src={person.photoUrl} alt="" loading="lazy" className="h-11 w-11 shrink-0 rounded-control object-cover" />
      ) : (
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-control bg-surface-2 text-[10px] text-subtle">yuzsiz</span>
      )}
      <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1.5">
        <Link to={`/shaxs/${person.id}`} target="_blank" className="truncate text-[13px] font-bold hover:text-primary hover:underline">
          {person.fullName}
        </Link>
        {person.biometricsStatus === 'tasdiqlangan' && <ScanFace size={13} className="shrink-0 text-success" aria-label="Yuzi bor" />}
      </div>
      <div className="truncate text-[11px] text-muted">
        {[person.groupOrPosition, person.hasPinfl ? 'JSHSHIR' : null, person.selfRegistered ? 'o‘zi ro‘yxatdan o‘tgan' : null,
          person.attendance ? `${person.attendance} kun davomat` : null, person.createdAt]
          .filter(Boolean)
          .join(' · ')}
      </div>
      </div>
    </div>
  );
}

export default function DuplicatePeopleModal({ open, onClose, onMerged }: { open: boolean; onClose: () => void; onMerged: () => void }) {
  const toast = useToast();
  const [groups, setGroups] = useState<DuplicateGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!open) return;
    setGroups(null);
    setError(null);
    getDuplicates()
      .then((result) => {
        setGroups(result);
        setSkipped(new Set());
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Ro‘yxatni olib bo‘lmadi'));
  }, [open, reload]);

  const selected = useMemo(
    () => (groups ?? []).filter((g) => g.mergeable !== false && !skipped.has(g.keeper.id)),
    [groups, skipped],
  );
  const reviewOnly = (groups ?? []).filter((g) => g.mergeable === false).length;
  const removeCount = selected.reduce((n, g) => n + g.duplicates.length, 0);

  const toggle = (id: string) =>
    setSkipped((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function merge() {
    const result = await mergeDuplicates(selected.map((g) => ({ keepId: g.keeper.id, removeIds: g.duplicates.map((d) => d.id) })));
    if (result.errors.length) toast.error(`${result.errors.length} ta guruh birlashmadi: ${result.errors[0]}`);
    if (result.mergedGroups) toast.success(`${result.mergedGroups} guruh birlashtirildi, ${result.removed} ta ortiqcha yozuv o‘chirildi`);
    setConfirming(false);
    onMerged();
    setReload((n) => n + 1);
  }

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        size="xl"
        title="Dublikatlar"
        description={
          groups
            ? `${groups.length - reviewOnly} guruh · ${removeCount} ta ortiqcha yozuv tanlangan${reviewOnly ? ` · ${reviewOnly} ta ko‘rib chiqish uchun` : ''}`
            : undefined
        }
        footer={
          <>
            <Button icon={ArrowLeft} onClick={onClose}>
              Yopish
            </Button>
            <Button variant="danger" disabled={!removeCount} onClick={() => setConfirming(true)}>
              Tanlanganlarni birlashtirish ({removeCount})
            </Button>
          </>
        }
      >
        {error ? (
          <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />
        ) : !groups ? (
          <div className="space-y-2">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : groups.length === 0 ? (
          <EmptyState title="Dublikat yo‘q" description="Har bir odamning bitta yozuvi bor" compact />
        ) : (
          <ul className="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
            {groups.map((group) => {
              const mergeable = group.mergeable !== false;
              const on = mergeable && !skipped.has(group.keeper.id);
              const similarity = group.faceSimilarity != null ? ` ${Math.round(group.faceSimilarity * 100)}%` : '';
              return (
                <li
                  key={`${group.reason ?? 'ism'}-${group.keeper.id}-${group.duplicates[0]?.id ?? ''}`}
                  className={cn('grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] items-start gap-2', !on && 'opacity-60')}
                >
                  {mergeable ? (
                    <input
                      id={`dup-${group.keeper.id}`}
                      type="checkbox"
                      checked={on}
                      onChange={() => toggle(group.keeper.id)}
                      aria-label={`${group.keeper.fullName} — birlashtirish`}
                      className="mt-3 h-4 w-4 accent-[rgb(var(--c-primary))]"
                    />
                  ) : (
                    <span className="w-4" />
                  )}
                  <PersonCell person={group.keeper} keep={mergeable} />
                  <div className="space-y-1">
                    {group.duplicates.map((dup) => (
                      <PersonCell key={dup.id} person={dup} />
                    ))}
                    {group.reason === 'ism_yuz' && <Badge tone="info">Yuzi ham mos{similarity}</Badge>}
                    {group.reason === 'yuz' && (
                      <p className="text-[11px] text-warning">
                        Yuzi bir xil{similarity}, ismi boshqa — birlashtirilmaydi. Rasmlardan biri noto‘g‘ri odamga
                        biriktirilgan bo‘lishi mumkin: shaxs kartasida yuzni tekshiring.
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {groups && groups.length > 0 && (
          <p className="mt-3 text-[12px] text-muted">Yashil — qoladi. O‘ngdagilarning yuzi, davomati va JSHSHIR unga ko‘chadi, keyin o‘chiriladi.</p>
        )}
      </Modal>

      <ConfirmDialog
        open={confirming}
        tone="danger"
        title={`${removeCount} ta yozuvni birlashtirish`}
        message="Ortiqcha yozuvlar o‘chiriladi. Ma’lumotlari saqlanadigan yozuvga ko‘chadi. Har birlashtirish audit jurnaliga yoziladi."
        confirmLabel="Birlashtirish"
        onCancel={() => setConfirming(false)}
        onConfirm={merge}
      />
    </>
  );
}
