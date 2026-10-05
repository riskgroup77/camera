/**
 * O'qituvchilar va darslar sahifalari (/oqituvchilar, /darslar) uchun
 * mijoz va sof yordamchi funksiyalar.
 *
 * `/api/situation/*` chaqiruvlari src/lib/situationApi.ts'da — bu yerda
 * faqat qolgan endpointlar (o'qituvchi kuni, davomat kameralari, dars
 * monitoring yozuvlari, xodim qidiruvi) va hisob-kitoblar.
 */
import { api, buildQuery, type CallOptions, type Page } from './apiClient';
import { UNIT_KIND_LABELS, type KafedraStat, type KafedraTeacher, type Lesson, type PeopleSort, type PersonRank } from './situationApi';
import type { Tone } from '../ui';
import type {
  AttendanceCameras,
  LessonRelation,
  LessonSession,
  PersonDay,
  StudentStaffRecord,
  TeacherDaySummary,
} from '../types';

// ───────────────────────────────────────────── Endpointlar

/** Kun bo'yicha xodimlar: kameralar tanigan yoki darsi bor har bir xodim. */
export function getTeachersDay(params: { date?: string; search?: string } = {}, opts?: CallOptions): Promise<TeacherDaySummary[]> {
  return api.get<TeacherDaySummary[]>(`/api/presence/teachers${buildQuery(params)}`, undefined, opts);
}

/** Bir odamning kuni: tashriflar (qaysi bino/xona) va jadvaldagi darslari. */
export function getPersonDay(personId: string, date?: string, opts?: CallOptions): Promise<PersonDay> {
  return api.get<PersonDay>(`/api/presence/people/${encodeURIComponent(personId)}/day${buildQuery({ date })}`, undefined, opts);
}

/** Davomat kameralari tashxisi (nega hech kim davomatga tushmayapti). */
export function getAttendanceCameras(opts?: CallOptions): Promise<AttendanceCameras> {
  return api.get<AttendanceCameras>('/api/presence/cameras', undefined, opts);
}

/** Xodimlarni F.I.Sh. bo'yicha qidirish (registerPeople huquqi kerak).
 *  Qidiruv matni so'rov tanasida — URL/access logga tushmaydi. */
export async function searchStaff(search: string, pageSize = 8, opts?: CallOptions): Promise<StudentStaffRecord[]> {
  const res = await api.post<Page<StudentStaffRecord>>(
    '/api/students-staff/search',
    { type: 'xodim', search, page: 1, pageSize, sort: 'name' },
    undefined,
    opts,
  );
  return res.items;
}

/** Xodim VA talabalarni birga qidirish — konsolning shaxs qidiruvi uchun.
 *  `searchStaff` bilan bitta endpoint, farqi shundaki tur bo'yicha
 *  filtrlamaydi (registerPeople huquqi kerak). */
export async function searchPeople(search: string, pageSize = 8, opts?: CallOptions): Promise<StudentStaffRecord[]> {
  const res = await api.post<Page<StudentStaffRecord>>(
    '/api/students-staff/search',
    { search, page: 1, pageSize, sort: 'name' },
    undefined,
    opts,
  );
  return res.items;
}

/** Davr ichidagi dars monitoring yozuvlari. API sana filtrini bilmaydi,
 *  lekin yozuvlarni sana bo'yicha kamayish tartibida beradi — shuning uchun
 *  `from`dan eski yozuvga yetganda sahifalashni to'xtatamiz. */
export async function getLessonSessionsInRange(
  from: string,
  to: string,
  params: { group?: string; faculty?: string } = {},
  opts?: CallOptions & { maxPages?: number },
): Promise<LessonSession[]> {
  const out: LessonSession[] = [];
  const maxPages = opts?.maxPages ?? 20;
  for (let page = 1; page <= maxPages; page += 1) {
    const res = await api.get<Page<LessonSession>>(
      `/api/lesson-sessions${buildQuery({ ...params, page, pageSize: 500 })}`,
      undefined,
      { signal: opts?.signal },
    );
    let reachedOlder = false;
    for (const item of res.items) {
      if (item.date < from) {
        reachedOlder = true;
        continue;
      }
      if (item.date <= to) out.push(item);
    }
    if (reachedOlder || page >= res.totalPages) break;
  }
  return out;
}

export function deleteLessonSession(id: string): Promise<void> {
  return api.del(`/api/lesson-sessions/${encodeURIComponent(id)}`);
}

/** Reyting ro'yxati. `order` MUHIM: server ro'yxatni tartiblab, keyin
 *  `limit` bilan KESADI — "eng erta keladigan"/"eng yuqori davomat"ni
 *  mijozda `reverse()` qilib olish mumkin emas, chunki kerakli odamlar
 *  kesilgan qismda qoladi. Shuning uchun tartib serverdan so'raladi. */
export function getPeopleRanking(
  params: { from: string; to: string; sort: PeopleSort; order: 'asc' | 'desc'; limit?: number },
  opts?: CallOptions,
): Promise<PersonRank[]> {
  return api.get<PersonRank[]>(`/api/situation/analytics/people${buildQuery({ type: 'xodim', ...params })}`, undefined, opts);
}

// ───────────────────────────────────────────── Yorliqlar va ohanglar

// Yagona ta'rif studentAttendance.ts'da — bu yerda faqat qayta eksport.
export { TEACHER_STATUS_META } from './studentAttendance';

export const LESSON_RELATION_TONE: Record<LessonRelation, Tone> = {
  oz_darsi: 'success',
  boshqa_dars: 'warning',
  darsi_boshqa_joyda: 'danger',
  darsdan_tashqari: 'neutral',
  jadval_yoq: 'neutral',
};

// ───────────────────────────────────────────── Hisob-kitoblar

export interface KafedraSummary {
  staffTotal: number;
  present: number;
  late: number;
  absent: number;
  notYet: number;
  noData: number;
  dayOff: number;
  lessons: number;
  lateLessons: number;
  missedLessons: number;
  /** Holati aniqlangan xodimlar: present + absent + notYet (rate maxraji). */
  decided: number;
  /** present / decided * 100 — backenddagi `Counts.rate` bilan AYNAN bir xil
   *  formula. Jami xodimga bo'lish noto'g'ri: yuzi ro'yxatdan o'tmagan
   *  (noData) va dam olishdagi xodimlar foizga umuman kirmaydi. */
  rate: number | null;
}

/** Kafedralar ro'yxatidan umumiy yig'indi (tepa plitkalar). */
export function summarizeKafedras(rows: readonly KafedraStat[]): KafedraSummary {
  const acc = rows.reduce(
    (sum, row) => ({
      staffTotal: sum.staffTotal + row.staffTotal,
      present: sum.present + row.present,
      late: sum.late + row.late,
      absent: sum.absent + row.absent,
      notYet: sum.notYet + row.notYet,
      noData: sum.noData + row.noData,
      dayOff: sum.dayOff + row.dayOff,
      lessons: sum.lessons + row.lessonsToday,
      lateLessons: sum.lateLessons + row.teacherLateLessons,
      missedLessons: sum.missedLessons + row.teacherMissedLessons,
    }),
    { staffTotal: 0, present: 0, late: 0, absent: 0, notYet: 0, noData: 0, dayOff: 0, lessons: 0, lateLessons: 0, missedLessons: 0 },
  );
  const decided = acc.present + acc.absent + acc.notYet;
  return { ...acc, decided, rate: decided ? Math.round((acc.present / decided) * 1000) / 10 : null };
}

/** Bo'linma yorlig'i. "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)" soxta
 *  bo'linmasi hamma joyda bir xil — "Biriktirilmagan" — deb ataladi: kartada
 *  "Lavozim", sahifasida "Biriktirilmagan" deyilsa bir xil bo'linma ikki xil
 *  ko'rinardi. */
export function unitKindLabel(unit: Pick<KafedraStat, 'kind' | 'unassigned'>): string {
  if (unit.unassigned) return 'Biriktirilmagan';
  return UNIT_KIND_LABELS[unit.kind] ?? unit.kind;
}

/** Kafedra davomati bo'laklari: o'z vaqtida / kech / kelmadi / hali kelmagan / ma'lumot yo'q. */
export function kafedraSegments(k: Pick<KafedraStat, 'present' | 'late' | 'absent' | 'notYet' | 'noData' | 'dayOff'>): Array<{ value: number; tone: Tone; label: string }> {
  return [
    { value: Math.max(0, k.present - k.late), tone: 'success' as const, label: 'Keldi' },
    { value: k.late, tone: 'warning' as const, label: 'Kech keldi' },
    { value: k.absent, tone: 'danger' as const, label: 'Kelmadi' },
    { value: k.notYet + k.noData + k.dayOff, tone: 'neutral' as const, label: "Hali kelmagan / ma'lumot yo'q" },
  ];
}

export interface PunctualitySummary {
  total: number;
  onTime: number;
  late: number;
  missed: number;
  pending: number;
  unknown: number;
  /** onTime / (onTime + late + missed) * 100; tekshirilgan dars yo'q → null. */
  rate: number | null;
}

/** Darslar bo'yicha o'qituvchi punktualligi. Kutilayotgan va noma'lum
 *  darslar foizga kirmaydi — "0%" emas, "ma'lumot yo'q". */
export function summarizePunctuality(lessons: readonly Pick<Lesson, 'teacherStatus'>[]): PunctualitySummary {
  const s: PunctualitySummary = { total: lessons.length, onTime: 0, late: 0, missed: 0, pending: 0, unknown: 0, rate: null };
  for (const lesson of lessons) {
    if (lesson.teacherStatus === 'oz_vaqtida') s.onTime += 1;
    else if (lesson.teacherStatus === 'kechikdi') s.late += 1;
    else if (lesson.teacherStatus === 'kelmadi') s.missed += 1;
    else if (lesson.teacherStatus === 'kutilmoqda') s.pending += 1;
    else s.unknown += 1;
  }
  const checked = s.onTime + s.late + s.missed;
  s.rate = checked ? Math.round((s.onTime / checked) * 1000) / 10 : null;
  return s;
}

/** Kechikish "og'irligi": avval bugun kelmagan/kechikkan darslar, keyin
 *  davrdagi o'z vaqtida foizi (past birinchi), keyin ism. */
export function latenessScore(t: KafedraTeacher): number {
  const today = t.lessonsMissed * 3 + t.lessonsLate * 2 + (t.status === 'kech_keldi' ? 1 : 0) + (t.status === 'kelmadi' ? 1.5 : 0);
  const periodBad = t.periodMissed * 1.5 + t.periodLate;
  return today * 100 + periodBad;
}

export type TeacherSort = 'lateness' | 'name' | 'onTime';

/** Ro'yxatdagi barcha tartiblar (Select shu tartibda chizadi). */
export const TEACHER_SORTS: readonly TeacherSort[] = ['lateness', 'onTime', 'name'];
/** Dars jadvalisiz hisoblab bo'lmaydigan tartiblar. */
export const LESSON_TEACHER_SORTS: readonly TeacherSort[] = ['onTime'];

/** Saqlangan yoki havoladan kelgan tartibni haqiqiy ro'yxatga keltiradi:
 *  olib tashlangan tartib (masalan eski "faollik") ham, dars jadvali yo'qda
 *  hisoblab bo'lmaydigani ham "kechikish"ga tushadi — Select bo'sh qolmasin. */
export function resolveTeacherSort(value: string | null | undefined, hasLessons: boolean): TeacherSort {
  const sort = TEACHER_SORTS.find((s) => s === value);
  if (!sort) return 'lateness';
  return !hasLessons && LESSON_TEACHER_SORTS.includes(sort) ? 'lateness' : sort;
}

export function sortTeachers(rows: readonly KafedraTeacher[], sort: TeacherSort): KafedraTeacher[] {
  const byName = (a: KafedraTeacher, b: KafedraTeacher) => a.fullName.localeCompare(b.fullName, 'uz');
  const nullLast = (v: number | null, dir: 1 | -1) => (v === null ? Number.POSITIVE_INFINITY : v * dir);
  const copy = [...rows];
  switch (sort) {
    case 'name':
      return copy.sort(byName);
    case 'onTime':
      return copy.sort((a, b) => nullLast(a.onTimeRate, 1) - nullLast(b.onTimeRate, 1) || byName(a, b));
    default:
      // Noma'lum (masalan saqlangan eski) tartib ham shu yerga tushadi.
      return copy.sort((a, b) => latenessScore(b) - latenessScore(a) || byName(a, b));
  }
}

/** Darsni AI to'liq kuzata oladimi: o'qituvchi, xona kamerasi va vaqt bor. */
export function isLessonTracked(lesson: Pick<Lesson, 'teacherId' | 'room' | 'startsAt'>): boolean {
  return Boolean(lesson.teacherId && lesson.room && lesson.startsAt);
}

/** Qidiruv: har bir so'z ismda bo'lishi kerak (apostrof turlari farqsiz). */
export function matchesName(name: string, query: string): boolean {
  const norm = (value: string) => value.toLowerCase().replace(/[‘’`ʻʼ]/g, "'");
  const hay = norm(name);
  return norm(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word));
}

export interface LessonAnalytics {
  sessions: number;
  avgAttention: number | null;
  avgActivity: number | null;
  sleepIncidents: number;
  checked: number;
  onTimeRate: number | null;
  attentionByDay: Array<{ date: string; label: string; diqqat: number; darslar: number }>;
  activityByTeacher: Array<{ teacher: string; faollik: number; darslar: number }>;
}

function average(values: number[]): number | null {
  if (!values.length) return null;
  return Math.round(values.reduce((sum, v) => sum + v, 0) / values.length);
}

/** Dars monitoring yozuvlaridan tahlil. O'rtachalar faqat O'LCHANGAN
 *  darslardan — o'lchovi yo'q dars "0%" emas. */
export function analyzeLessonSessions(sessions: readonly LessonSession[]): LessonAnalytics {
  const attention = sessions.map((s) => s.attentionScore).filter((v): v is number => v !== null);
  const activity = sessions.map((s) => s.teacherActivityScore).filter((v): v is number => v !== null);
  const checked = sessions.filter((s) => s.teacherOnTime !== null);
  const onTime = checked.filter((s) => s.teacherOnTime).length;

  const byDay = new Map<string, { total: number; count: number }>();
  for (const s of sessions) {
    if (s.attentionScore === null) continue;
    const entry = byDay.get(s.date) ?? { total: 0, count: 0 };
    entry.total += s.attentionScore;
    entry.count += 1;
    byDay.set(s.date, entry);
  }
  const byTeacher = new Map<string, { total: number; count: number }>();
  for (const s of sessions) {
    if (s.teacherActivityScore === null) continue;
    const entry = byTeacher.get(s.teacher) ?? { total: 0, count: 0 };
    entry.total += s.teacherActivityScore;
    entry.count += 1;
    byTeacher.set(s.teacher, entry);
  }

  return {
    sessions: sessions.length,
    avgAttention: average(attention),
    avgActivity: average(activity),
    sleepIncidents: sessions.reduce((sum, s) => sum + s.sleepIncidents, 0),
    checked: checked.length,
    onTimeRate: checked.length ? Math.round((onTime / checked.length) * 100) : null,
    attentionByDay: Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, e]) => ({ date, label: `${date.slice(8, 10)}.${date.slice(5, 7)}`, diqqat: Math.round(e.total / e.count), darslar: e.count })),
    activityByTeacher: Array.from(byTeacher.entries())
      .map(([teacher, e]) => ({ teacher: teacher.replace(/^(Prof\.|Dots\.)\s*/, ''), faollik: Math.round(e.total / e.count), darslar: e.count }))
      .sort((a, b) => b.faollik - a.faollik || a.teacher.localeCompare(b.teacher)),
  };
}

/** "08:05:12" → "08:05". */
export function hhmm(value: string | null | undefined): string {
  return value ? value.slice(0, 5) : '—';
}
