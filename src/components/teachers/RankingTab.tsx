import { useMemo, useState } from 'react';
import { Trophy } from 'lucide-react';
import { Badge, Card, DateRangePicker, EmptyState, ErrorState, SearchInput, Tabs, Toolbar, formatPercent, formatUzDate, type Tone } from '../../ui';
import { situationPaths, type PeopleSort, type PersonRank } from '../../lib/situationApi';
import { getPeopleRanking, matchesName } from '../../lib/teachersApi';
import { useViewDate } from '../../lib/viewDate';
import { RankingList, type RankingItem } from '../analytics';
import { ANALYTICS_PRESETS, useAnalyticsPeriod, useUrlChoice } from './analyticsPeriod';
import { useLoader } from './useLoader';

type Mode = 'late' | 'absent' | 'early' | 'best';

/** `order` serverga beriladi — ro'yxat KESILISHIDAN oldin tartiblansin
 *  (mijozdagi `reverse()` kesilgan 500 ta ichidagina ishlardi va "eng erta
 *  keladigan" o'rniga "eng kech keladigan"ning bir qismini ko'rsatardi). */
const MODES: Array<{ id: Mode; label: string; sort: PeopleSort; order: 'asc' | 'desc' }> = [
  { id: 'late', label: "Eng ko'p kechikkan", sort: 'late', order: 'desc' },
  { id: 'absent', label: "Eng ko'p kelmagan", sort: 'absent', order: 'desc' },
  { id: 'early', label: 'Eng erta keladigan', sort: 'arrival', order: 'asc' },
  { id: 'best', label: 'Eng yuqori davomat', sort: 'rate', order: 'desc' },
];
const MODE_IDS: readonly Mode[] = MODES.map((m) => m.id);
const LIMIT = 500;
const SHOWN = 100;

const STREAK_LABEL: Record<NonNullable<PersonRank['streakKind']>, string> = {
  kech_keldi: 'ketma-ket kech',
  kelmadi: 'ketma-ket kelmadi',
  aralash: 'ketma-ket muammo',
};

export function StreakBadge({ p }: { p: Pick<PersonRank, 'streak' | 'streakKind'> }) {
  if (p.streak < 2 || !p.streakKind) return null;
  return (
    <Badge tone={p.streakKind === 'kech_keldi' ? 'warning' : 'danger'} title="Hozirgacha davom etayotgan ketma-ket kunlar">
      {p.streak} kun {STREAK_LABEL[p.streakKind]}
    </Badge>
  );
}

function toItem(p: PersonRank, mode: Mode, max: number, personLink: (id: string) => string): RankingItem {
  const worked = p.presentDays + p.absentDays;
  let value: string;
  let hint: string;
  let tone: Tone;
  let bar: number | null;
  switch (mode) {
    case 'late':
      value = `${p.lateDays} kun`;
      hint = `${worked} ish kunidan · ${p.avgArrival ?? '—'}`;
      tone = 'warning';
      bar = max ? (p.lateDays / max) * 100 : 0;
      break;
    case 'absent':
      value = `${p.absentDays} kun`;
      hint = p.lastSeen ? `oxirgi: ${formatUzDate(p.lastSeen, { year: false })}` : "ko'rinmagan";
      tone = 'danger';
      bar = max ? (p.absentDays / max) * 100 : 0;
      break;
    case 'early':
      value = p.avgArrival ?? '—';
      hint = `o'rtacha · ${p.presentDays} kun`;
      tone = 'success';
      bar = null;
      break;
    default:
      value = formatPercent(p.rate, 1);
      hint = `${p.presentDays}/${worked} kun · ${p.lateDays} kech`;
      tone = 'success';
      bar = p.rate;
  }
  return {
    id: p.id,
    name: p.fullName,
    photoUrl: p.photoUrl,
    subtitle: p.unit,
    value,
    valueHint: hint,
    valueTone: tone,
    bar,
    badges: <StreakBadge p={p} />,
    to: personLink(p.id),
  };
}

/** "Reyting" tabi: xodimlar reytingi (kechikish, kelmaslik, erta kelish, davomat). */
export function RankingTab() {
  const [period, setPeriod] = useAnalyticsPeriod();
  // Reyting turi URL'da: yangilash va havolani ulashish tanlovni yo'qotmaydi.
  const [mode, setMode] = useUrlChoice<Mode>('reyting', MODE_IDS, 'late');
  const [search, setSearch] = useState('');
  const { withDate } = useViewDate();
  const cfg = MODES.find((m) => m.id === mode) ?? MODES[0];
  const people = useLoader(
    `p:${period.from}:${period.to}:${cfg.sort}:${cfg.order}`,
    (signal) => getPeopleRanking({ from: period.from, to: period.to, sort: cfg.sort, order: cfg.order, limit: LIMIT }, { signal }),
    { group: 'people' },
  );

  // Server LIMIT ta yozuv qaytaradi: aynan shuncha kelgan bo'lsa ro'yxat
  // manbadayoq kesilgan. Ilgari sahifa faqat "birinchi 100 kishi" derdi va
  // qolgan 400+ kishini qidiruv bilan ham topib bo'lmasligi aytilmasdi.
  const serverCapped = (people.data?.length ?? 0) >= LIMIT;
  const { items, truncated } = useMemo(() => {
    let rows = people.data ?? [];
    if (mode === 'late') rows = rows.filter((p) => p.lateDays > 0);
    if (mode === 'absent') rows = rows.filter((p) => p.absentDays > 0);
    if (mode === 'early') rows = rows.filter((p) => p.avgArrivalMinutes !== null);
    if (mode === 'best') {
      rows = rows
        .filter((p) => p.rate !== null)
        .slice()
        .sort((a, b) => (b.rate ?? 0) - (a.rate ?? 0) || b.presentDays - a.presentDays || a.lateDays - b.lateDays);
    }
    if (search.trim()) rows = rows.filter((p) => matchesName(p.fullName, search) || matchesName(p.unit, search));
    const max = Math.max(1, ...rows.map((p) => (mode === 'absent' ? p.absentDays : p.lateDays)));
    return {
      items: rows.slice(0, SHOWN).map((p) => toItem(p, mode, max, (id) => withDate(situationPaths.person(id)))),
      truncated: rows.length > SHOWN,
    };
  }, [people.data, mode, search, withDate]);

  return (
    <>
      <Toolbar>
        <DateRangePicker value={period} onChange={setPeriod} presets={ANALYTICS_PRESETS} size="sm" showSummary={false} />
        <SearchInput value={search} onChange={setSearch} placeholder="Ism yoki bo'linma…" ariaLabel="Reytingda qidirish" />
      </Toolbar>
      <Tabs variant="segmented" value={mode} onChange={setMode} ariaLabel="Reyting turi" tabs={MODES.map(({ id, label }) => ({ id, label }))} className="max-w-full overflow-x-auto" />
      <Card>
        {people.error && !people.data ? (
          <ErrorState message={people.error} onRetry={people.reload} />
        ) : !people.loading && items.length === 0 ? (
          <EmptyState
            icon={Trophy}
            title="Ro'yxat bo'sh"
            description={
              search
                ? 'Qidiruvga mos xodim topilmadi.'
                : "Bu davrda bunday holat qayd etilmagan. Esda tuting: ro'yxatga faqat yuzi ro'yxatdan o'tgan xodimlar tushadi."
            }
          />
        ) : (
          <RankingList items={items} loading={people.loading} ariaLabel={cfg.label} />
        )}
        {(truncated || serverCapped) && (
          <p className="mt-3 text-center text-xs text-muted">
            {truncated && `Birinchi ${SHOWN} kishi ko'rsatilmoqda — ro'yxatni qisqartirish uchun qidiruvdan foydalaning.`}
            {serverCapped && ` Bu reytingga «${cfg.label}» bo'yicha eng yuqori ${LIMIT} kishi olinadi — qidiruv ham shu ${LIMIT} kishi ichida ishlaydi.`}
          </p>
        )}
      </Card>
    </>
  );
}
