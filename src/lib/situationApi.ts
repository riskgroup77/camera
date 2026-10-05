/**
 * Situatsion markaz API'si (`/api/situation/*`) uchun tiplangan mijoz.
 *
 * Shartnoma: camera-api/docs/SITUATION_API.md — interfeyslar u yerdagi
 * TS ta'riflar bilan bir xil (camelCase). Barcha funksiyalar ixtiyoriy
 * `AbortSignal` qabul qiladi (filtr/sana o'zgarganda eski so'rovni bekor
 * qilish uchun). Token apiClient orqali avtomatik qo'shiladi.
 */
import { api, buildQuery, type CallOptions } from './apiClient';

// ───────────────────────────────────────────── Umumiy tiplar

/** Odamning bir kundagi holati. */
export type AttendanceStatus = 'keldi' | 'kech_keldi' | 'kelmadi' | 'dam_olish' | 'kutilmoqda' | 'malumot_yoq';

export type BiometricsStatus = 'tasdiqlangan' | 'kutilmoqda' | 'yoq';

/** Bir to'plam odamning kunlik davomati. `total = present + absent + dayOff + notYet + noData`. */
export interface Counts {
  total: number;
  enrolled: number;
  present: number;
  /** present ichidan kech kelganlar */
  late: number;
  absent: number;
  dayOff: number;
  notYet: number;
  noData: number;
  /** present / (present + absent + notYet) * 100; asos 0 → null */
  rate: number | null;
}

export type LessonState = 'upcoming' | 'ongoing' | 'finished';

export type TeacherStatus = 'oz_vaqtida' | 'kechikdi' | 'kelmadi' | 'kutilmoqda' | 'nomalum';

export interface Lesson {
  id: string;
  date: string;
  subject: string;
  groupName: string;
  faculty: string;
  teacher: string;
  teacherId: string | null;
  teacherPhotoUrl: string | null;
  startsAt: string | null;
  endsAt: string | null;
  room: string | null;
  building: string | null;
  state: LessonState;
  teacherStatus: TeacherStatus;
  teacherArrivedAt: string | null;
  teacherOnTime: boolean | null;
  expected: number;
  present: number;
  late: number;
  /** yakunlanmagan darsda null */
  absent: number | null;
  seen: number;
  finalized: boolean;
  attentionScore: number | null;
  activityScore: number | null;
  sleepIncidents: number;
}

// ───────────────────────────────────────────── 1. Overview

export interface FacultyCounts extends Counts {
  /** "Fakultetsiz" uchun null */
  id: string | null;
  name: string;
}

export interface LastArrival {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  type: 'talaba' | 'xodim';
  unit: string;
  faculty: string | null;
  time: string;
  status: string;
}

export interface Overview {
  date: string;
  isToday: boolean;
  generatedAt: string;
  students: Counts;
  staff: Counts;
  teachers: { scheduled: number; onTime: number; late: number; absent: number; unknown: number };
  lessons: { total: number; finished: number; ongoing: number; upcoming: number; avgAttention: number | null };
  cameras: { total: number; active: number; online: number; videoFlowing: number };
  events: { open: number; today: number; highOpen: number; overdue: number };
  byFaculty: FacultyCounts[];
  /** students.enrolled / students.total >= 5% */
  studentsDataAvailable: boolean;
  studentsEnrolledPct: number | null;
  /** Soat bo'yicha kelganlar; *Late — shundan "kech_keldi" (eski server bermasa — undefined). */
  arrivalsByHour: Array<{ hour: number; students: number; staff: number; studentsLate?: number; staffLate?: number }>;
  lastArrivals: LastArrival[];
  /** Kechikish chegarasi "HH:MM" (ish vaqti sozlamasidan) — kelish grafigidagi chiziq. */
  lateAfterStudents?: string | null;
  lateAfterStaff?: string | null;
}

// ───────────────────────────────────────────── 2–4. Fakultet / guruh

export interface GroupStat extends Counts {
  name: string;
  facultyId: string | null;
  faculty: string | null;
  course: number | null;
  curator: null;
}

export interface CourseBlock {
  course: number | null;
  label: string;
  groups: GroupStat[];
  totals: Counts;
}

export interface FacultyDetail {
  id: string;
  name: string;
  date: string;
  isToday: boolean;
  totals: Counts;
  courses: CourseBlock[];
}

export interface GroupStudent {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  status: AttendanceStatus;
  checkIn: string | null;
  checkOut: string | null;
  biometricsStatus: BiometricsStatus;
}

export interface TrendPoint {
  date: string;
  rate: number | null;
  present: number;
  late: number;
  absent: number;
}

export interface GroupDetail {
  date: string;
  isToday: boolean;
  group: { name: string; facultyId: string | null; faculty: string | null; course: number | null; totals: Counts };
  students: GroupStudent[];
  lessons: Lesson[];
  trend: TrendPoint[];
}

// ───────────────────────────────────────────── 5–6. Kafedralar

/** Bo'linma turi (matndan aniqlanadi). */
export type UnitKind = 'kafedra' | 'dekanat' | 'bolim' | 'lavozim';

export interface KafedraStat {
  id: string;
  name: string;
  kind: UnitKind;
  building: string | null;
  unassigned: boolean;
  staffTotal: number;
  enrolled: number;
  present: number;
  late: number;
  absent: number;
  dayOff: number;
  notYet: number;
  noData: number;
  rate: number | null;
  lessonsToday: number;
  teacherLateLessons: number;
  teacherMissedLessons: number;
}

export interface KafedraTeacher {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  position: string;
  biometricsStatus: string;
  status: AttendanceStatus;
  checkIn: string | null;
  checkOut: string | null;
  lessonsScheduled: number;
  lessonsOnTime: number;
  lessonsLate: number;
  lessonsMissed: number;
  periodLessons: number;
  periodOnTime: number;
  periodLate: number;
  periodMissed: number;
  onTimeRate: number | null;
  avgActivityScore: number | null;
  periodPresentDays: number;
  periodLateDays: number;
  periodAbsentDays: number;
}

export interface KafedraDetail {
  id: string;
  name: string;
  kind: UnitKind;
  building: string | null;
  unassigned: boolean;
  date: string;
  isToday: boolean;
  today: Counts;
  teachers: KafedraTeacher[];
  period: {
    dateFrom: string;
    dateTo: string;
    lessons: number;
    onTime: number;
    late: number;
    missed: number;
    unknown: number;
    onTimeRate: number | null;
    avgActivityScore: number | null;
    presentDays: number;
    lateDays: number;
    absentDays: number;
  };
}

// ───────────────────────────────────────────── 7. Darslar

export interface LessonPage {
  items: Lesson[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  date: string;
  counts: { upcoming: number; ongoing: number; finished: number };
}

export interface LessonQuery {
  date?: string;
  facultyId?: string;
  group?: string;
  teacherId?: string;
  departmentId?: string;
  status?: LessonState;
  page?: number;
  pageSize?: number;
}

// ───────────────────────────────────────────── 8. Shaxs profili

export type LessonAttendanceStatus = 'keldi' | 'kech_keldi' | 'kelmadi';

export interface PersonLesson extends Lesson {
  attendanceStatus: LessonAttendanceStatus | null;
  firstSeen: string | null;
}

export interface CalendarDay {
  date: string;
  status: AttendanceStatus;
  checkIn: string | null;
  checkOut: string | null;
}

export interface PersonVisit {
  id: string;
  date: string;
  camera: string;
  building: string | null;
  zone: string | null;
  firstSeen: string;
  lastSeen: string;
  durationMinutes: number;
  sightings: number;
}

export interface PersonInfo {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  photoUrl: string | null;
  initials: string;
  facultyId: string | null;
  faculty: string | null;
  unit: string;
  /** HEMIS lavozimi (xodim). */
  position?: string | null;
  /** Ro'yxatdan o'tishda saqlangan tomonlar (old, chap, o'ng): 0..3. */
  photoAngles?: number;
  group: string | null;
  course: number | null;
  /** HEMIS'da topilmagan talaba o'zi yozgan guruh. */
  reportedGroup?: string | null;
  departmentId: string | null;
  department: string | null;
  biometricsStatus: string;
  parentNotify: boolean;
  active: boolean;
}

export interface PersonProfile {
  person: PersonInfo;
  dateFrom: string;
  dateTo: string;
  calendar: CalendarDay[];
  totals: {
    days: number;
    present: number;
    late: number;
    absent: number;
    dayOff: number;
    noData: number;
    rate: number | null;
    avgArrival: string | null;
  };
  lessons: PersonLesson[];
  recentVisits: PersonVisit[];
}

// ───────────────────────────────────────────── Dars davomati (lesson-sessions)

export interface LessonAttendanceRow {
  studentId: string;
  fullName: string;
  /** null — dars hali yakunlanmagan */
  status: LessonAttendanceStatus | null;
  firstSeenAt: string | null;
  sightings: number;
}

export interface LessonAttendance {
  lessonSessionId: string;
  group: string;
  subject: string;
  scheduledStartTime: string | null;
  finalized: boolean;
  present: number;
  late: number;
  absent: number;
  rows: LessonAttendanceRow[];
}

// ───────────────────────────────────────────── 9–13. Tahlil

export type PersonType = 'xodim' | 'talaba';

/** Umumiy tahlil parametrlari (standart: bugungacha 30 kun, type=xodim). */
export interface AnalyticsRange {
  from?: string;
  to?: string;
  type?: PersonType;
}

export interface PeriodKpis {
  rate: number | null;
  avgArrival: string | null;
  /** kun boshidan daqiqa */
  avgArrivalMinutes: number | null;
  present: number;
  late: number;
  absent: number;
  punctualPct: number | null;
  daysCovered: number;
}

export interface AnalyticsDaily {
  date: string;
  present: number;
  late: number;
  absent: number;
  expected: number;
  rate: number | null;
  avgArrival: string | null;
}

export interface AnalyticsSummary {
  type: PersonType;
  dateFrom: string;
  dateTo: string;
  previousFrom: string;
  previousTo: string;
  current: PeriodKpis;
  previous: PeriodKpis;
  /** current − previous; avgArrivalMinutes > 0 — kechroq kelishgan */
  delta: {
    rate: number | null;
    avgArrivalMinutes: number | null;
    late: number;
    absent: number;
    punctualPct: number | null;
  };
  daily: AnalyticsDaily[];
}

export type WeekdayLabel = 'Du' | 'Se' | 'Cho' | 'Pa' | 'Ju' | 'Sha';

export interface HeatmapWeekday {
  /** ISO 1=Du .. 6=Sha */
  weekday: number;
  label: WeekdayLabel;
  /** `hours` bilan bir xil tartib */
  counts: number[];
  total: number;
  present: number;
  late: number;
  lateRate: number | null;
}

export interface Heatmap {
  type: PersonType;
  dateFrom: string;
  dateTo: string;
  hours: number[];
  weekdays: HeatmapWeekday[];
  max: number;
  outside: number;
}

export type UnitSort = 'rate' | 'late' | 'absent' | 'arrival' | 'punctual' | 'trend' | 'headcount' | 'name';

export interface UnitAnalytics {
  id: string;
  name: string;
  kind: UnitKind | 'guruh';
  headcount: number;
  enrolled: number;
  presentDays: number;
  lateDays: number;
  absentDays: number;
  rate: number | null;
  avgArrival: string | null;
  avgArrivalMinutes: number | null;
  punctualPct: number | null;
  previousRate: number | null;
  /** rate − previousRate */
  trend: number | null;
}

export type PeopleSort = 'late' | 'absent' | 'arrival' | 'rate';

export interface PersonRank {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  unitId: string;
  unit: string;
  presentDays: number;
  lateDays: number;
  absentDays: number;
  rate: number | null;
  avgArrival: string | null;
  avgArrivalMinutes: number | null;
  /** oxirgi kelgan kun (YYYY-MM-DD) */
  lastSeen: string | null;
  /** hozirgi uzluksiz kelmadi/kech_keldi kunlari */
  streak: number;
  streakKind: 'kelmadi' | 'kech_keldi' | 'aralash' | null;
}

export interface ChronicPerson {
  id: string;
  fullName: string;
  photoUrl: string | null;
  initials: string;
  unitId: string;
  unit: string;
  absentDays: number;
  lateDays: number;
  absentDates: string[];
  lateDates: string[];
  reasons: Array<'kelmadi' | 'kech_keldi'>;
}

// ───────────────────────────────────────────── 14–16. Ro'yxatga olish (enrollment)

export interface EnrollCounts {
  total: number;
  confirmed: number;
  pending: number;
  none: number;
  /** confirmed / total * 100 */
  pct: number | null;
}

export interface Enrollment {
  students: EnrollCounts;
  staff: EnrollCounts;
  byFaculty: Array<EnrollCounts & { id: string | null; name: string }>;
  studentsDataAvailable: boolean;
}

export interface EnrollGroup {
  name: string;
  facultyId: string | null;
  faculty: string | null;
  course: number | null;
  total: number;
  confirmed: number;
  pending: number;
  pct: number | null;
}

export interface EnrollMissing {
  group: string;
  total: number;
  missing: Array<{ id: string; fullName: string; initials: string; biometricsStatus: 'kutilmoqda' | 'yoq' }>;
  /** QR uchun (guruh nomi va kod bilan) */
  enrollUrl: string;
  /** Guruhning ro'yxatdan o'tish kodi — kartada chop etiladi. */
  enrollCode: string;
}

// ───────────────────────────────────────────── 17. Devor ekrani

export interface WallUnit {
  id: string;
  name: string;
  kind: string;
  total: number;
  present: number;
  rate: number | null;
}

export interface WallEvent {
  id: string;
  moduleName: string;
  cameraName: string;
  building: string;
  time: string;
  status: string;
}

export interface Wall {
  date: string;
  generatedAt: string;
  students: Counts;
  staff: Counts;
  studentsDataAvailable: boolean;
  topUnits: WallUnit[];
  bottomUnits: WallUnit[];
  lastArrivals: LastArrival[];
  highEvents: WallEvent[];
  camerasOnline: number;
  camerasTotal: number;
  enrollment: Enrollment;
  spotlight: Array<{ kind: 'unit' | 'group'; id: string; name: string; rate: number | null }>;
}

// ───────────────────────────────────────────── Funksiyalar

const BASE = '/api/situation';

export function getOverview(date?: string, opts?: CallOptions): Promise<Overview> {
  return api.get<Overview>(`${BASE}/overview${buildQuery({ date })}`, undefined, opts);
}

export function getFaculty(facultyId: string, date?: string, opts?: CallOptions): Promise<FacultyDetail> {
  return api.get<FacultyDetail>(`${BASE}/faculties/${encodeURIComponent(facultyId)}${buildQuery({ date })}`, undefined, opts);
}

export function getGroups(
  params: { date?: string; facultyId?: string; course?: number; search?: string } = {},
  opts?: CallOptions,
): Promise<GroupStat[]> {
  return api.get<GroupStat[]>(`${BASE}/groups${buildQuery(params)}`, undefined, opts);
}

export function getGroup(groupName: string, date?: string, opts?: CallOptions): Promise<GroupDetail> {
  return api.get<GroupDetail>(`${BASE}/groups/${encodeURIComponent(groupName)}${buildQuery({ date })}`, undefined, opts);
}

export type UnitKindFilter = 'kafedra' | 'dekanat' | 'bolim' | 'all';

export function getKafedras(date?: string, opts?: CallOptions, kind?: UnitKindFilter): Promise<KafedraStat[]> {
  return api.get<KafedraStat[]>(`${BASE}/kafedras${buildQuery({ date, kind })}`, undefined, opts);
}

export function getKafedra(
  departmentId: string,
  params: { date?: string; from?: string; to?: string } = {},
  opts?: CallOptions,
): Promise<KafedraDetail> {
  return api.get<KafedraDetail>(`${BASE}/kafedras/${encodeURIComponent(departmentId)}${buildQuery(params)}`, undefined, opts);
}

export function getLessons(params: LessonQuery = {}, opts?: CallOptions): Promise<LessonPage> {
  return api.get<LessonPage>(`${BASE}/lessons${buildQuery({ ...params })}`, undefined, opts);
}

export function getPerson(
  personId: string,
  params: { from?: string; to?: string } = {},
  opts?: CallOptions,
): Promise<PersonProfile> {
  return api.get<PersonProfile>(`${BASE}/people/${encodeURIComponent(personId)}${buildQuery(params)}`, undefined, opts);
}

export function getLessonAttendance(lessonId: string, opts?: CallOptions): Promise<LessonAttendance> {
  return api.get<LessonAttendance>(`/api/lesson-sessions/${encodeURIComponent(lessonId)}/attendance`, undefined, opts);
}

export function getAnalyticsSummary(params: AnalyticsRange = {}, opts?: CallOptions): Promise<AnalyticsSummary> {
  return api.get<AnalyticsSummary>(`${BASE}/analytics/summary${buildQuery({ ...params })}`, undefined, opts);
}

export function getAnalyticsHeatmap(params: AnalyticsRange = {}, opts?: CallOptions): Promise<Heatmap> {
  return api.get<Heatmap>(`${BASE}/analytics/heatmap${buildQuery({ ...params })}`, undefined, opts);
}

export function getAnalyticsUnits(
  params: AnalyticsRange & { kind?: UnitKind | 'guruh' | 'all'; sort?: UnitSort; order?: 'asc' | 'desc' } = {},
  opts?: CallOptions,
): Promise<UnitAnalytics[]> {
  return api.get<UnitAnalytics[]>(`${BASE}/analytics/units${buildQuery({ ...params })}`, undefined, opts);
}

export function getAnalyticsPeople(
  params: AnalyticsRange & { sort?: PeopleSort; unitId?: string; limit?: number } = {},
  opts?: CallOptions,
): Promise<PersonRank[]> {
  return api.get<PersonRank[]>(`${BASE}/analytics/people${buildQuery({ ...params })}`, undefined, opts);
}

export function getAnalyticsChronic(
  params: AnalyticsRange & { minAbsent?: number; minLate?: number } = {},
  opts?: CallOptions,
): Promise<ChronicPerson[]> {
  return api.get<ChronicPerson[]>(`${BASE}/analytics/chronic${buildQuery({ ...params })}`, undefined, opts);
}

export function getEnrollment(opts?: CallOptions): Promise<Enrollment> {
  return api.get<Enrollment>(`${BASE}/enrollment`, undefined, opts);
}

export function getEnrollmentGroups(
  params: { facultyId?: string; course?: number } = {},
  opts?: CallOptions,
): Promise<EnrollGroup[]> {
  return api.get<EnrollGroup[]>(`${BASE}/enrollment/groups${buildQuery(params)}`, undefined, opts);
}

export function getEnrollmentMissing(groupName: string, opts?: CallOptions): Promise<EnrollMissing> {
  return api.get<EnrollMissing>(`${BASE}/enrollment/groups/${encodeURIComponent(groupName)}/missing`, undefined, opts);
}

export function getWall(opts?: CallOptions): Promise<Wall> {
  return api.get<Wall>(`${BASE}/wall`, undefined, opts);
}

// ───────────────────────────────────────────── Yorliqlar

export const UNIT_KIND_LABELS: Record<UnitKind | 'guruh', string> = {
  kafedra: 'Kafedra',
  dekanat: 'Dekanat',
  bolim: "Bo'lim",
  lavozim: 'Lavozim',
  guruh: 'Guruh',
};

// Davomat/dars yorliqlari bitta joyda: src/ui/status.ts (umumiy holatlar) va
// src/lib/studentAttendance.ts (dars kesimidagi holatlar). Bu yerda nusxasi
// bo'lgani uchun "kech keldi" ikki xil yozilib qolgandi.

/** Frontend marshrutlari (davomat sahifalari orasida havola uchun). */
export const situationPaths = {
  faculties: '/talabalar',
  faculty: (id: string | null) => `/talabalar/fakultet/${id ? encodeURIComponent(id) : NO_FACULTY_ID}`,
  group: (name: string) => `/talabalar/guruh/${encodeURIComponent(name)}`,
  person: (id: string) => `/shaxs/${encodeURIComponent(id)}`,
  kafedra: (id: string) => `/oqituvchilar/kafedra/${encodeURIComponent(id)}`,
};

/** "Fakultetsiz" (id null) talabalar uchun URL segmenti. */
export const NO_FACULTY_ID = 'fakultetsiz';

// ───────────────────────────────────────────── Holat bo'yicha odamlar (sanoq ortidagi ro'yxat)

/** kelgan = keldi + kech_keldi; yuzsiz — yuzi bazada yo'q (kamera tanimaydi). */
export type PeopleStatusKey =
  | 'hammasi' | 'kelgan' | 'keldi' | 'kech_keldi' | 'kelmadi' | 'kutilmoqda' | 'yuzsiz' | 'dam_olish' | 'malumot_yoq';

export interface StatusPerson {
  id: string;
  fullName: string;
  type: PersonType;
  group: string;
  course: number | null;
  faculty: string | null;
  status: AttendanceStatus;
  checkIn: string | null;
  biometricsStatus: BiometricsStatus;
  /** Xodim: lavozimi va tuzilmadagi bo'linmasi. */
  position?: string | null;
  unit?: string | null;
}

export type StatusCounts = Record<
  'hammasi' | 'kelgan' | 'keldi' | 'kechKeldi' | 'kelmadi' | 'kutilmoqda' | 'yuzsiz' | 'damOlish' | 'malumotYoq',
  number
>;

export interface StatusPeoplePage {
  date: string;
  counts: StatusCounts;
  total: number;
  page: number;
  pageSize: number;
  items: StatusPerson[];
}

export interface StatusPeopleQuery {
  date?: string;
  status?: PeopleStatusKey;
  type?: PersonType;
  facultyId?: string;
  course?: number;
  group?: string;
  /** Xodimlar: kafedra / bo'lim (getKafedras id). */
  departmentId?: string;
  /** Xodimlar: tuzilmadagi bo'linma (ichki bo'linmalari bilan); 'yoq' — bog'lanmaganlar. */
  orgUnitId?: string;
  positionGroup?: PositionGroup;
  position?: string;
  search?: string;
  page?: number;
  pageSize?: number;
  /** Kelish grafigidagi ustun: shu soatda (0-23) kelganlar. */
  arrivalHour?: number;
}

export function getPeopleStatus(params: StatusPeopleQuery = {}, opts?: CallOptions): Promise<StatusPeoplePage> {
  return api.get<StatusPeoplePage>(`${BASE}/people-status${buildQuery({ ...params })}`, undefined, opts);
}

/** Holat kaliti -> counts maydoni. */
export const STATUS_COUNT_KEY: Record<PeopleStatusKey, keyof StatusCounts> = {
  hammasi: 'hammasi',
  kelgan: 'kelgan',
  keldi: 'keldi',
  kech_keldi: 'kechKeldi',
  kelmadi: 'kelmadi',
  kutilmoqda: 'kutilmoqda',
  yuzsiz: 'yuzsiz',
  dam_olish: 'damOlish',
  malumot_yoq: 'malumotYoq',
};

// ───────────────────────────────────────────── Institut tuzilmasi (HEMIS)

export type PositionGroup = 'oqituvchi' | 'mamuriy' | 'texnik';

export const POSITION_GROUP_LABEL: Record<PositionGroup, string> = {
  oqituvchi: 'Professor-o‘qituvchilar',
  mamuriy: 'Ma’muriy xodimlar',
  texnik: 'Texnik xodimlar',
};

export interface OrgNode {
  id: string;
  name: string;
  kind: string;
  kindLabel: string;
  depth: number;
  parentId: string | null;
  total: number;
  present: number;
  absent: number;
  /** Bugun, hali kelmagan (kun tugamagan). */
  notYet: number;
  noData: number;
}

export interface OrgPosition {
  name: string;
  group: PositionGroup | null;
  total: number;
  present: number;
  absent: number;
  /** Bugun, hali kelmagan (kun tugamagan). */
  notYet: number;
  noData: number;
}

export interface OrgTree {
  date: string;
  units: OrgNode[];
  positions: OrgPosition[];
  positionGroups: Record<string, number>;
}

export function getOrgTree(date?: string, opts?: CallOptions): Promise<OrgTree> {
  return api.get<OrgTree>(`${BASE}/tuzilma${buildQuery({ date })}`, undefined, opts);
}


/** Ism bo'yicha qisqa qidiruv — davomat huquqi yetarli (reestr qidiruvi registerPeople talab qiladi). */
export interface PersonHit {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  faculty: string | null;
  groupOrPosition: string | null;
  biometricsStatus: string;
  biometricPhotoUrl: string | null;
}

export function searchPeopleByName(
  q: string,
  params: { type?: 'talaba' | 'xodim'; limit?: number } = {},
  opts: CallOptions = {},
): Promise<PersonHit[]> {
  return api.get<PersonHit[]>(`${BASE}/odam-qidirish${buildQuery({ q, ...params })}`, undefined, opts);
}

/** Kun holati: ish kuni yoki dam olish/bayram (va oxirgi ish kuni). */
export interface DayInfo {
  date: string;
  isWorkDay: boolean;
  reason: string | null;
  lastWorkDay: string | null;
}

export function dayInfoPath(date: string): string {
  return `${BASE}/kun${buildQuery({ date })}`;
}
