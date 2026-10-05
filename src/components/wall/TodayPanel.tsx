import { CalendarCheck2, GraduationCap, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Counts } from '../../lib/situationApi';
import type { EnrollCounts } from '../../lib/wallApi';
import { MicroLabel, cn, formatPercent } from '../../ui';
import { RAG_LETTER, RAG_LABEL, RAG_TEXT, RATE_RAG, rag } from '../../ui/rag';
import { AnimatedNumber, WallPanel, WallRing } from './primitives';

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="min-w-0 border-s border-border ps-[0.6em] first:border-s-0 first:ps-0">
      <div className={cn('intel-code text-[1.9em] font-semibold leading-none', tone)}>
        <AnimatedNumber value={value} />
      </div>
      <MicroLabel className="intel-micro-wrap mt-[0.5em] block !text-[0.6em]">{label}</MicroLabel>
    </div>
  );
}

function Block({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col justify-center border border-border bg-surface-2 px-[0.9em] py-[0.7em]">
      <div className="mb-[0.6em] flex items-center gap-[0.45em] [&>svg]:h-[1em] [&>svg]:w-[1em] [&>svg]:text-muted">
        {icon}
        <MicroLabel className="!text-[0.65em] !text-fg">{title}</MicroLabel>
      </div>
      {children}
    </div>
  );
}

/** O'lchangan / o'lchanmagan farqi — zaldan o'qiladigan qisqa yozuv:
 *  "1 030 / 6 912 yuz". Foiz faqat yuzi ro'yxatdan o'tganlar bo'yicha
 *  o'lchanadi; qamrovsiz "92%" butun institut davomati bo'lib o'qilardi. */
export function coverageNote(counts: Counts): string | null {
  if (counts.total <= 0 || counts.enrolled >= counts.total) return null;
  const n = (v: number) => v.toLocaleString('ru-RU');
  return `${n(counts.enrolled)} / ${n(counts.total)} yuz`;
}

function AttendanceBlock({ counts }: { counts: Counts }) {
  const expected = counts.present + counts.absent + counts.notYet;
  // Hech kim kutilmagan bo'lsa foiz "0%" emas, O'LCHANMAGAN.
  const measured = expected > 0 && counts.rate !== null;
  const tone = rag(measured ? counts.rate : null, RATE_RAG);
  const note = coverageNote(counts);
  return (
    <div>
    <div className="flex items-center gap-[1.1em]">
      {/* Svetofor ustuni: rang + harf (Y/S/Q) — rangni ajratmaydigan
          odam ham, uzoqdan qaragan odam ham bir xil o'qiydi. */}
      <div className="flex shrink-0 flex-col items-center gap-[0.35em]">
        <WallRing value={measured ? counts.rate : null} size={6.2} />
        <span className={cn('intel-code text-[0.85em] font-bold', RAG_TEXT[tone])} title={RAG_LABEL[tone]}>
          {RAG_LETTER[tone]}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-[0.3em] leading-none">
          <AnimatedNumber value={counts.present} className="text-[3.4em] font-semibold leading-[0.85] text-fg" />
          <span className="intel-code text-[1.3em] text-muted">/ {expected.toLocaleString('ru-RU')}</span>
        </div>
        <MicroLabel className="mt-[0.5em] block !text-[0.6em]">keldi</MicroLabel>
        <div className="mt-[0.8em] grid grid-cols-3 gap-[0.6em]">
          <Metric label="kech" value={counts.late} tone="text-warning" />
          <Metric label="kelmadi" value={counts.absent} tone="text-danger" />
          <Metric label="kutilmoqda" value={counts.notYet} tone="text-muted" />
        </div>
      </div>
    </div>
      {note && <div className="intel-code mt-[0.55em] border-t border-border pt-[0.4em] text-[0.68em] text-muted">{note}</div>}
    </div>
  );
}

function EnrollmentBlock({ enroll }: { enroll: EnrollCounts }) {
  const pct = enroll.pct ?? 0;
  return (
    <div>
      <div className="flex items-center gap-[1.1em]">
        <WallRing value={pct} size={6.2} tone="primary" label={formatPercent(pct)} sublabel="yuz topshirgan" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-[0.3em] leading-none">
            <AnimatedNumber value={enroll.confirmed} className="text-[2.6em] font-semibold text-fg" />
            <span className="text-[1.2em] tabular-nums text-muted">/ {enroll.total.toLocaleString('ru-RU')}</span>
          </div>
        </div>
      </div>
      {enroll.pending > 0 && (
        <div className="mt-[0.5em] text-[0.72em] text-muted">
          Tekshiruvda <span className="intel-code text-fg">{enroll.pending.toLocaleString('ru-RU')}</span>
        </div>
      )}
    </div>
  );
}

/** Fakultetlar bo'yicha yuz topshirish — davomat faqat yuzi borlar uchun
 *  yuritiladi, shuning uchun eng orqada qolgan fakultet ekranda ko'rinsin. */
function FacultyEnrollBlock({ rows }: { rows: Array<EnrollCounts & { id: string | null; name: string }> }) {
  const shown = rows.filter((r) => r.id && r.total > 0).sort((a, b) => (a.pct ?? 0) - (b.pct ?? 0)).slice(0, 5);
  if (shown.length === 0) return null;
  return (
    <ul className="flex flex-col gap-[0.35em] text-[0.72em]">
      {shown.map((r) => (
        <li key={r.id} className="grid grid-cols-[minmax(0,1fr)_7em_3.2em] items-center gap-[0.6em]">
          <span className="truncate text-fg">{r.name.replace(/ fakulteti$/i, '')}</span>
          <span className="h-[0.45em] overflow-hidden rounded-full bg-surface-2">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.min(100, r.pct ?? 0)}%` }} />
          </span>
          <span className="intel-code text-right text-muted">{formatPercent(r.pct ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
}

export function TodayPanel({
  students,
  staff,
  studentsDataAvailable,
  studentsEnroll,
  facultyEnroll = [],
}: {
  students: Counts;
  staff: Counts;
  studentsDataAvailable: boolean;
  studentsEnroll: EnrollCounts;
  facultyEnroll?: Array<EnrollCounts & { id: string | null; name: string }>;
}) {
  return (
    <WallPanel area="A" title="Bugungi davomat" icon={<CalendarCheck2 />}>
      <div className="flex min-h-0 flex-1 flex-col gap-[0.8em]">
        <Block icon={<Users />} title="Xodimlar">
          <AttendanceBlock counts={staff} />
        </Block>
        <Block icon={<GraduationCap />} title="Talabalar">
          {studentsDataAvailable ? <AttendanceBlock counts={students} /> : <EnrollmentBlock enroll={studentsEnroll} />}
        </Block>
        {facultyEnroll.length > 0 && (
          <Block icon={<GraduationCap />} title="Yuz topshirish — fakultetlar">
            <FacultyEnrollBlock rows={facultyEnroll} />
          </Block>
        )}
      </div>
    </WallPanel>
  );
}
