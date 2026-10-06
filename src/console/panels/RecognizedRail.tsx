import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ExternalLink, MapPin, UserRound } from 'lucide-react';
import { ButtonLink, Modal, attendanceMeta, cn, formatPercent, initials } from '../../ui';
import { isAbortError } from '../../lib/apiClient';
import { getPerson, situationPaths, type PersonProfile } from '../../lib/situationApi';
import type { SeenPerson } from '../recognizedPeople';
import { EASE } from '../motion';

const TYPE_LABEL: Record<string, string> = { talaba: 'Talaba', xodim: 'Xodim' };

function clock(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

/** Ro'yxatdan o'tishdagi surat; bo'lmasa yoki ochilmasa — bosh harflar. */
function Photo({ url, name, className }: { url: string | null; name: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  return (
    <span className={cn('relative block shrink-0 overflow-hidden bg-neutral-800', className)}>
      {url && !failed ? (
        <img src={url} alt="" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <span className="grid h-full w-full place-items-center text-[13px] font-semibold text-white/70">{initials(name)}</span>
      )}
    </span>
  );
}

/** Tanlangan kamerada tanilganlar — video yonidagi qora joyda ustun.
 *  Kadrdagilar yuqorida (yashil nuqta), chiqib ketganlar — oxirgi ko'ringan
 *  vaqti bilan pastda. Karta bosilsa — to'liq ma'lumot. */
export function RecognizedRail({ people, onPick }: { people: SeenPerson[]; onPick: (person: SeenPerson) => void }) {
  if (people.length === 0) return null;
  const inFrame = people.filter((person) => person.inFrame).length;
  return (
    <div
      className="absolute bottom-2 right-2 top-2 z-[3] flex w-[min(32%,200px)] flex-col gap-1.5"
      aria-label="Tanilganlar"
    >
      <div className="flex items-center gap-1.5 rounded-full bg-black/65 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur">
        <UserRound size={12} aria-hidden="true" />
        <span className="flex-1">Tanilganlar</span>
        <span className="tabular-nums text-emerald-300" title="Hozir kadrda">{inFrame}</span>
        <span className="tabular-nums text-white/50">/ {people.length}</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-0.5 [scrollbar-width:thin]">
        <AnimatePresence initial={false}>
          {people.map((person) => (
            <motion.button
              key={person.id}
              type="button"
              layout
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: person.inFrame ? 1 : 0.72, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.25, ease: EASE }}
              onClick={() => onPick(person)}
              title={`${person.name} — to'liq ma'lumot`}
              className={cn(
                'flex shrink-0 items-stretch gap-2 rounded-[8px] border bg-black/65 p-1.5 text-left text-white backdrop-blur transition hover:bg-black/80',
                person.inFrame ? 'border-emerald-400/60' : 'border-white/10 hover:border-white/30',
              )}
            >
              <Photo url={person.photoUrl} name={person.name} className="h-[60px] w-[48px] rounded-[5px]" />
              <span className="flex min-w-0 flex-1 flex-col justify-between py-0.5">
                <span className="line-clamp-2 text-[12px] font-semibold leading-tight">{person.name}</span>
                {person.unit && <span className="truncate text-[10px] text-white/60">{person.unit}</span>}
                <span className="flex items-center gap-1 text-[10px]">
                  {person.inFrame ? (
                    <>
                      <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-400 text-emerald-400" aria-hidden="true" />
                      <span className="text-emerald-300">Kadrda</span>
                    </>
                  ) : (
                    <span className="tabular-nums text-white/50">{clock(person.lastSeen)}</span>
                  )}
                  {person.similarity != null && (
                    <span className="ms-auto tabular-nums text-white/45" title="O'xshashlik">
                      {Math.round(person.similarity * 100)}%
                    </span>
                  )}
                </span>
              </span>
            </motion.button>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

/** Kartani bosganda: shaxs haqida to'liq ma'lumot (GET /api/situation/people/{id}). */
export function PersonQuickView({ person, onClose }: { person: SeenPerson | null; onClose: () => void }) {
  const [profile, setProfile] = useState<PersonProfile | null>(null);
  const [failed, setFailed] = useState(false);
  const personId = person?.id ?? null;

  useEffect(() => {
    if (!personId) return;
    const controller = new AbortController();
    setProfile(null);
    setFailed(false);
    getPerson(personId, {}, { signal: controller.signal })
      .then(setProfile)
      .catch((error) => {
        if (!isAbortError(error)) setFailed(true);
      });
    return () => controller.abort();
  }, [personId]);

  if (!person) return null;
  const info = profile?.person;
  const today = profile?.calendar.at(-1) ?? null;
  const todayMeta = today ? attendanceMeta(today.status) : null;
  const facts: Array<[string, string | null | undefined]> = info
    ? [
        ['Turi', TYPE_LABEL[info.type] ?? info.type],
        ['Fakultet', info.faculty],
        [info.type === 'talaba' ? 'Guruh' : "Bo'lim", info.type === 'talaba' ? info.group ?? info.reportedGroup ?? info.unit : info.department ?? info.unit],
        ['Kurs', info.course ? `${info.course}-kurs` : null],
        ['Lavozim', info.position],
        ['Biometrika', info.biometricsStatus === 'tasdiqlangan' ? `Tasdiqlangan (${info.photoAngles ?? 1}/3 surat)` : info.biometricsStatus],
      ]
    : [
        ['Turi', person.type ? TYPE_LABEL[person.type] ?? person.type : null],
        [person.type === 'talaba' ? 'Guruh' : 'Lavozim', person.unit],
      ];

  return (
    <Modal open onClose={onClose} title="Tanilgan shaxs" size="lg">
      <div className="flex flex-col gap-4 p-4 sm:flex-row">
        <Photo url={info?.photoUrl ?? person.photoUrl} name={person.name} className="h-[150px] w-[120px] self-center rounded-[8px] sm:self-start" />
        <div className="min-w-0 flex-1">
          <h3 className="text-[17px] font-semibold leading-tight text-fg">{info?.fullName ?? person.name}</h3>
          <p className="mt-1 text-[12px] text-muted">
            Kamerada: {person.inFrame ? 'hozir kadrda' : `oxirgi marta ${clock(person.lastSeen)}`}
            {person.similarity != null && ` · o'xshashlik ${Math.round(person.similarity * 100)}%`}
          </p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
            {facts
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted">{label}</dt>
                  <dd className="min-w-0 break-words text-fg">{value}</dd>
                </div>
              ))}
          </dl>
        </div>
      </div>

      {profile && (
        <div className="grid grid-cols-2 gap-2 border-t border-border px-4 py-3 sm:grid-cols-4">
          <Fact label="Bugun" value={todayMeta?.label ?? '—'} hint={today?.checkIn ? `kirdi ${today.checkIn.slice(0, 5)}` : undefined} />
          <Fact label="Davomat" value={profile.totals.rate != null ? formatPercent(profile.totals.rate) : '—'} hint={`${profile.dateFrom.slice(5)} – ${profile.dateTo.slice(5)}`} />
          <Fact label="Kech keldi" value={`${profile.totals.late} kun`} />
          <Fact label="O'rtacha kelish" value={profile.totals.avgArrival?.slice(0, 5) ?? '—'} />
        </div>
      )}

      {profile && profile.recentVisits.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          <p className="mb-1.5 text-[12px] font-semibold text-muted">Oxirgi ko'rinishlar</p>
          <ul className="flex flex-col gap-1 text-[12px]">
            {profile.recentVisits.slice(0, 5).map((visit) => (
              <li key={visit.id} className="flex items-center gap-2">
                <MapPin size={12} className="shrink-0 text-subtle" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-fg">
                  {visit.camera}
                  {visit.building ? ` · ${visit.building}` : ''}
                </span>
                <span className="shrink-0 tabular-nums text-muted">
                  {visit.date.slice(5)} {visit.firstSeen.slice(0, 5)}–{visit.lastSeen.slice(0, 5)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!profile && !failed && <p className="border-t border-border px-4 py-3 text-[12px] text-muted">Ma'lumot yuklanmoqda…</p>}
      {failed && (
        <p className="border-t border-border px-4 py-3 text-[12px] text-danger">To'liq ma'lumotni olib bo'lmadi (ruxsat yoki tarmoq).</p>
      )}

      <div className="flex justify-end border-t border-border px-4 py-3">
        <ButtonLink to={situationPaths.person(person.id)} size="sm" variant="secondary">
          <ExternalLink size={14} aria-hidden="true" /> To'liq sahifa
        </ButtonLink>
      </div>
    </Modal>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[6px] bg-surface-2 px-2.5 py-2">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="text-[14px] font-semibold tabular-nums text-fg">{value}</p>
      {hint && <p className="text-[10px] text-subtle">{hint}</p>}
    </div>
  );
}
