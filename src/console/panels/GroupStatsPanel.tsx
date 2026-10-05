import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../lib/apiClient';
import {
  getOverview,
  getPeopleStatus,
  type Lesson,
  type Overview,
  type PeopleStatusKey,
  type StatusCounts,
} from '../../lib/situationApi';
import { Modal, cn } from '../../ui';
import StatusCounters, { COUNTER_META, type CounterKey } from '../../components/situation/StatusCounters';
import StatusPeopleTable from '../../components/situation/StatusPeopleTable';
import PdfButton from '../../components/situation/PdfButton';
import ArrivalsChart from '../../components/situation/ArrivalsChart';
import { bucketsFromPeople, hourRange } from '../../lib/arrivals';
import { TONE_TEXT, criterionShort, workingCriteria } from '../../lib/groupCriteriaApi';
import Panel from '../Panel';
import type { GroupLive } from '../useGroupLive';
import type { GroupCriteriaState } from '../useGroupCriteria';
import type { NazoratSelection } from '../nazoratSelection';
import { groupCounters, lessonSeenIds } from './GroupTablePanel';

/**
 * NAZORAT — o'ng pastki panel: tanlangan guruh (yoki butun institut)
 * bo'yicha jonli ma'lumot. Har son bosiladi — kimligi ko'rinadi:
 * guruhda chap jadval filtrlanadi, institut bo'yicha esa ro'yxat oynasi ochiladi.
 */

const TEACHER_LABEL: Record<string, { text: string; tone: string }> = {
  oz_vaqtida: { text: 'o‘qituvchi o‘z vaqtida keldi', tone: 'text-success' },
  kechikdi: { text: 'o‘qituvchi kechikdi', tone: 'text-warning' },
  kelmadi: { text: 'o‘qituvchi kelmadi', tone: 'text-danger' },
  kutilmoqda: { text: 'o‘qituvchi kutilmoqda', tone: 'text-muted' },
  nomalum: { text: 'o‘qituvchi holati noma’lum', tone: 'text-muted' },
};

const INSTITUTE_KEYS: CounterKey[] = ['hammasi', 'kelgan', 'kech_keldi', 'kelmadi', 'kutilmoqda', 'yuzsiz'];
const COUNT_FIELD: Partial<Record<CounterKey, keyof StatusCounts>> = {
  hammasi: 'hammasi',
  kelgan: 'kelgan',
  kech_keldi: 'kechKeldi',
  kelmadi: 'kelmadi',
  kutilmoqda: 'kutilmoqda',
  yuzsiz: 'yuzsiz',
};

function clock(iso: string | null): string {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('uz-UZ', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Tashkent' }).format(
    new Date(iso),
  );
}

function LessonCard({
  lesson,
  seenCount,
  onPick,
}: {
  lesson: Lesson;
  seenCount: number | null;
  onPick: (key: CounterKey) => void;
}) {
  const teacher = TEACHER_LABEL[lesson.teacherStatus] ?? TEACHER_LABEL.nomalum;
  const seen = seenCount ?? lesson.seen;
  const missing = Math.max(0, lesson.expected - seen);
  return (
    <div className="rounded-control border border-border bg-surface px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-success">Hozirgi dars</span>
        <b className="text-[14px] text-fg">{lesson.subject}</b>
        <span className="text-[12px] tabular-nums text-muted">
          {clock(lesson.startsAt)}–{clock(lesson.endsAt)}
        </span>
      </div>
      <div className="mt-0.5 text-[12px] text-muted">
        {[lesson.room, lesson.building].filter(Boolean).join(', ') || 'xona ko‘rsatilmagan'} · {lesson.teacher}
        {' · '}
        <span className={teacher.tone}>{teacher.text}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-3 text-[12px]">
        <span>
          Kutilgan: <b className="tabular-nums">{lesson.expected}</b>
        </span>
        <button type="button" onClick={() => onPick('darsda')} className="text-success hover:underline">
          Darsda: <b className="tabular-nums">{seen}</b>
        </button>
        <button type="button" onClick={() => onPick('darsda_emas')} className="text-danger hover:underline">
          Darsda yo‘q: <b className="tabular-nums">{missing}</b>
        </button>
        {lesson.late > 0 && (
          <span className="text-warning">
            Kech: <b className="tabular-nums">{lesson.late}</b>
          </span>
        )}
      </div>
    </div>
  );
}

/** Guruh bo'yicha kriteriyalar — bosilsa chapdagi jadval kriteriyalarga o'tadi. */
function CriteriaSummary({ criteria, onOpen }: { criteria: GroupCriteriaState; onOpen: () => void }) {
  if (criteria.error) return <p className="text-[12px] text-danger">{criteria.error}</p>;
  if (!criteria.data) return <p className="text-[12px] text-muted">Kriteriyalar yuklanmoqda…</p>;
  return (
    <div className="rounded-control border border-border bg-surface px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold text-fg">Kriteriyalar</span>
        <button type="button" onClick={onOpen} className="text-[11px] text-primary hover:underline">
          har talaba bo‘yicha →
        </button>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1">
        {workingCriteria(criteria.data.criteria).map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={onOpen}
            title={`${c.code ? `${c.code}. ` : ''}${c.label} — ${c.unavailable ?? c.description}`}
            className="flex items-baseline justify-between gap-2 rounded px-1 text-left text-[12px] hover:bg-surface-2"
          >
            <span className="truncate text-muted">
              {c.code ? <span className="me-1 text-[10px] text-subtle">{c.code}</span> : null}
              {criterionShort(c)}
            </span>
            <b className={cn('shrink-0 tabular-nums', TONE_TEXT[c.tone])}>{c.indicator}</b>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function GroupStatsPanel({
  selection,
  live,
  criteria,
  canCriteria,
  date,
  isToday,
  pulse,
  expanded,
  onExpand,
  area,
}: {
  selection: NazoratSelection;
  live: GroupLive;
  criteria: GroupCriteriaState;
  canCriteria: boolean;
  date: string;
  isToday: boolean;
  pulse: number;
  expanded: boolean;
  onExpand: (id: string | null) => void;
  area?: string;
}) {
  const { who, group, status, setStatus } = selection;
  const students = who === 'talaba';
  // Talaba guruhi tanlangan — guruh ko'rinishi; aks holda (institut yoki kafedra) — server sanoqlari.
  const groupView = students && Boolean(group);
  const orgUnitId = !students && group ? group : undefined;
  const [counts, setCounts] = useState<StatusCounts | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<PeopleStatusKey | null>(null);
  // Kelish grafigidagi bosilgan ustun (soat) — shu soatda kelganlar ro'yxati.
  const [arrivalHour, setArrivalHour] = useState<number | null>(null);

  // Institut va guruh — kelish grafigi (overview: kechikish chegarasi va
  // institut ustunlari; guruh ustunlari — guruh talabalaridan); kafedra/
  // bo'linma tanlanganda soatlik sanoq unga mos kelmaydi — o'rniga sanoqlari.
  useEffect(() => {
    const controller = new AbortController();
    const request = orgUnitId
      ? getPeopleStatus({ date, type: who, orgUnitId, pageSize: 1 }, { signal: controller.signal }).then((page) => {
          setCounts(page.counts);
        })
      : getOverview(date, { signal: controller.signal }).then(setOverview);
    request
      .then(() => setError(null))
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof ApiError ? err.message : "Ma'lumotni olib bo'lmadi");
      });
    return () => controller.abort();
  }, [groupView, who, orgUnitId, date, pulse]);

  const seen = lessonSeenIds(live);
  const info = live.detail?.group;
  // Guruh tanlanganda grafik yo'qolmaydi — o'sha guruh talabalarining kelishi.
  const groupArrivals = useMemo(() => bucketsFromPeople(live.detail?.students ?? []), [live.detail]);

  const body = groupView ? (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto px-3 pb-3">
      <div className="text-[12px] text-muted">
        {[info?.faculty, info?.course ? `${info.course}-kurs` : null].filter(Boolean).join(' · ') || '—'}
        {info?.totals.rate != null && (
          <span className="ms-2 font-semibold text-fg">davomat {Math.round(info.totals.rate)}%</span>
        )}
      </div>
      {live.detail && (
        <ArrivalsChart
          buckets={groupArrivals.buckets}
          who="talaba"
          lateAfter={overview?.lateAfterStudents}
          isToday={isToday}
          untimed={groupArrivals.untimed}
          onPick={setArrivalHour}
          className="min-h-[190px] shrink-0"
        />
      )}
      <StatusCounters
        items={groupCounters(live.detail?.students ?? [], null)}
        active={status}
        onPick={setStatus}
        size="sm"
      />
      {live.current ? (
        <LessonCard lesson={live.current} seenCount={seen ? seen.size : null} onPick={setStatus} />
      ) : (
        <div className="rounded-control border border-dashed border-border px-3 py-2 text-[12px] text-muted">
          {isToday ? 'Hozir bu guruhda dars yo‘q' : 'O‘tgan kun'}
          {live.next && (
            <>
              {' · keyingi: '}
              <b className="text-fg">{live.next.subject}</b> {clock(live.next.startsAt)}
              {live.next.room ? `, ${live.next.room}` : ''}
            </>
          )}
        </div>
      )}
      {canCriteria && <CriteriaSummary criteria={criteria} onOpen={() => selection.setView('kriteriyalar')} />}
    </div>
  ) : orgUnitId ? (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto px-3 pb-3">
      <StatusCounters
        items={INSTITUTE_KEYS.map((key) => ({ key, value: counts ? counts[COUNT_FIELD[key]!] : null }))}
        onPick={(key) => setListing(key as PeopleStatusKey)}
        size="sm"
      />
      <p className={cn('text-[11px]', error ? 'text-danger' : 'text-muted')}>{error ?? 'Sonni bosing — kimligi ko‘rinadi.'}</p>
    </div>
  ) : (
    // Kelish oqimi — butun institut bo'yicha; panelning hamma joyini oladi.
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto px-3 pb-3">
      {overview ? (
        <ArrivalsChart
          buckets={overview.arrivalsByHour}
          who={who}
          lateAfter={students ? overview.lateAfterStudents : overview.lateAfterStaff}
          untimed={(students ? overview.arrivalsUntimedStudents : overview.arrivalsUntimedStaff) ?? 0}
          isToday={isToday}
          onPick={setArrivalHour}
          className="min-h-[190px] flex-1"
        />
      ) : (
        <div className={cn('text-[12px]', error ? 'text-danger' : 'text-muted')}>{error ?? 'Yuklanmoqda…'}</div>
      )}
      {overview && error && <p className="text-[11px] text-danger">{error}</p>}
      {students && <p className="text-[11px] text-muted">Guruh bo‘yicha batafsil — chapdagi jadvaldan guruhni tanlang.</p>}
    </div>
  );

  return (
    <>
      <Panel
        id="group-stats"
        title={
          // "jonli" faqat bugun uchun — o'tgan kun arxiv.
          groupView
            ? `${group} — ${isToday ? 'jonli holat' : 'kun holati'}`
            : students
              ? `Institut — talabalar${isToday ? ', jonli' : ''}`
              : `O‘qituvchi va xodimlar${isToday ? ' — jonli' : ''}`
        }
        live={isToday}
        expanded={expanded}
        onExpand={onExpand}
        area={area}
        clickToExpand={false}
        full={body}
      >
        {expanded ? null : body}
      </Panel>
      <Modal
        open={listing !== null}
        onClose={() => setListing(null)}
        size="xl"
        title={listing ? `${students ? 'Talabalar' : 'O‘qituvchi va xodimlar'}: ${COUNTER_META[listing as CounterKey]?.label ?? listing}` : ''}
        description={date}
        footer={
          listing ? (
            <PdfButton
              path="/api/situation/pdf/people"
              params={{ date, type: who, orgUnitId, status: listing }}
              filename={`${who}-${listing}-${date}`}
            />
          ) : undefined
        }
      >
        {listing && <StatusPeopleTable query={{ date, type: who, orgUnitId }} status={listing} refreshKey={pulse} maxHeight="60vh" />}
      </Modal>
      <Modal
        open={arrivalHour !== null}
        onClose={() => setArrivalHour(null)}
        size="xl"
        title={
          arrivalHour !== null
            ? `${groupView ? `${group} guruhi` : students ? 'Talabalar' : 'O‘qituvchi va xodimlar'}: ${hourRange(arrivalHour)} da kelganlar`
            : ''
        }
        description={date}
        footer={
          arrivalHour !== null ? (
            <PdfButton
              path="/api/situation/pdf/people"
              params={{ date, type: who, status: 'kelgan', arrivalHour, group: groupView ? group : undefined }}
              filename={`${groupView ? `${group}-` : `${who}-`}kelgan-${String(arrivalHour).padStart(2, '0')}-${date}`}
            />
          ) : undefined
        }
      >
        {arrivalHour !== null && (
          <StatusPeopleTable
            query={{ date, type: who, arrivalHour, group: groupView ? group : undefined }}
            status="kelgan"
            refreshKey={pulse}
            maxHeight="60vh"
          />
        )}
      </Modal>
    </>
  );
}
