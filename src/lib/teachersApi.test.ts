import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  analyzeLessonSessions,
  getLessonSessionsInRange,
  hhmm,
  isLessonTracked,
  matchesName,
  resolveTeacherSort,
  sortTeachers,
  summarizeKafedras,
  summarizePunctuality,
} from './teachersApi';
import type { KafedraStat, KafedraTeacher } from './situationApi';
import type { LessonSession } from '../types';

function kafedra(partial: Partial<KafedraStat>): KafedraStat {
  return {
    id: 'k',
    name: 'K',
    kind: 'kafedra',
    building: null,
    unassigned: false,
    staffTotal: 0,
    enrolled: 0,
    present: 0,
    late: 0,
    absent: 0,
    dayOff: 0,
    notYet: 0,
    noData: 0,
    rate: null,
    lessonsToday: 0,
    teacherLateLessons: 0,
    teacherMissedLessons: 0,
    ...partial,
  };
}

function teacher(partial: Partial<KafedraTeacher>): KafedraTeacher {
  return {
    id: partial.fullName ?? 't',
    fullName: 'T',
    photoUrl: null,
    initials: 'T',
    position: 'Kafedra',
    biometricsStatus: 'tasdiqlangan',
    status: 'keldi',
    checkIn: null,
    checkOut: null,
    lessonsScheduled: 0,
    lessonsOnTime: 0,
    lessonsLate: 0,
    lessonsMissed: 0,
    periodLessons: 0,
    periodOnTime: 0,
    periodLate: 0,
    periodMissed: 0,
    onTimeRate: null,
    avgActivityScore: null,
    periodPresentDays: 0,
    periodLateDays: 0,
    periodAbsentDays: 0,
    ...partial,
  };
}

function session(partial: Partial<LessonSession>): LessonSession {
  return {
    id: 's',
    date: '2026-09-19',
    group: 'DI-2301',
    faculty: 'Davolash ishi',
    teacher: 'Aliyev Vali',
    subject: 'Anatomiya',
    attentionScore: null,
    sleepIncidents: 0,
    teacherActivityScore: null,
    teacherOnTime: null,
    ...partial,
  };
}

describe('summarizeKafedras', () => {
  it('sums staff and lesson counters including the unassigned row', () => {
    const s = summarizeKafedras([
      kafedra({ staffTotal: 7, present: 6, late: 1, absent: 1, lessonsToday: 10, teacherLateLessons: 2, teacherMissedLessons: 1 }),
      kafedra({ id: 'unassigned', unassigned: true, staffTotal: 3, present: 2, lessonsToday: 1 }),
    ]);
    expect(s).toMatchObject({ staffTotal: 10, present: 8, late: 1, absent: 1, lessons: 11, lateLessons: 2, missedLessons: 1 });
  });

  it('returns zeros for an empty list', () => {
    expect(summarizeKafedras([]).staffTotal).toBe(0);
    expect(summarizeKafedras([]).rate).toBeNull();
  });

  // Foiz maxraji backenddagi `Counts.rate` bilan bir xil bo'lishi SHART:
  // aks holda tepa plitka bilan har bir bo'linma kartasidagi halqa turli
  // foizni ko'rsatadi (kartada 90%, plitkada 50%).
  it('computes the rate like the backend: present / (present + absent + notYet)', () => {
    const s = summarizeKafedras([
      // 20 xodim: 10 keldi, 2 kelmadi, 0 hali kelmagan, 8 ning yuzi yo'q.
      kafedra({ staffTotal: 20, present: 10, late: 2, absent: 2, notYet: 0, noData: 8 }),
    ]);
    expect(s.decided).toBe(12);
    expect(s.rate).toBe(83.3);
    expect(s.noData).toBe(8);
  });

  it('counts people who have not arrived yet in the denominator', () => {
    const s = summarizeKafedras([kafedra({ staffTotal: 10, present: 4, absent: 1, notYet: 5 })]);
    expect(s.decided).toBe(10);
    expect(s.rate).toBe(40);
  });
});

describe('summarizePunctuality', () => {
  it('excludes pending and unknown lessons from the rate', () => {
    const s = summarizePunctuality([
      { teacherStatus: 'oz_vaqtida' },
      { teacherStatus: 'oz_vaqtida' },
      { teacherStatus: 'oz_vaqtida' },
      { teacherStatus: 'kechikdi' },
      { teacherStatus: 'kutilmoqda' },
      { teacherStatus: 'nomalum' },
    ]);
    expect(s).toMatchObject({ total: 6, onTime: 3, late: 1, missed: 0, pending: 1, unknown: 1, rate: 75 });
  });

  it('gives null (not 0%) when nothing was checked', () => {
    expect(summarizePunctuality([{ teacherStatus: 'kutilmoqda' }]).rate).toBeNull();
  });
});

describe('sortTeachers', () => {
  const rows = [
    teacher({ fullName: 'Bobur', onTimeRate: 90, avgActivityScore: 60 }),
    teacher({ fullName: 'Anvar', lessonsLate: 1, onTimeRate: 70, avgActivityScore: 80 }),
    teacher({ fullName: 'Dilnoza', lessonsMissed: 1, onTimeRate: null, avgActivityScore: null }),
  ];

  it('puts missed/late lessons first when sorting by lateness', () => {
    expect(sortTeachers(rows, 'lateness').map((t) => t.fullName)).toEqual(['Dilnoza', 'Anvar', 'Bobur']);
  });

  it('sorts on-time rate ascending with unknown rates last', () => {
    expect(sortTeachers(rows, 'onTime').map((t) => t.fullName)).toEqual(['Anvar', 'Bobur', 'Dilnoza']);
  });

  it('sorts by name', () => {
    expect(sortTeachers(rows, 'name').map((t) => t.fullName)).toEqual(['Anvar', 'Bobur', 'Dilnoza']);
  });

  it('does not mutate the input', () => {
    const copy = [...rows];
    sortTeachers(rows, 'lateness');
    expect(rows).toEqual(copy);
  });
});

describe('resolveTeacherSort', () => {
  it('keeps a known sort', () => {
    expect(resolveTeacherSort('name', true)).toBe('name');
    expect(resolveTeacherSort('onTime', true)).toBe('onTime');
  });

  it('falls back when the stored sort no longer exists (olib tashlangan "faollik")', () => {
    expect(resolveTeacherSort('activity', true)).toBe('lateness');
    expect(resolveTeacherSort('', true)).toBe('lateness');
    expect(resolveTeacherSort(null, true)).toBe('lateness');
  });

  it('falls back when there are no lessons to compute the sort from', () => {
    expect(resolveTeacherSort('onTime', false)).toBe('lateness');
    expect(resolveTeacherSort('name', false)).toBe('name');
  });
});

describe('analyzeLessonSessions', () => {
  it('averages only measured sessions and groups by day and teacher', () => {
    const a = analyzeLessonSessions([
      session({ date: '2026-09-18', attentionScore: 80, teacherActivityScore: 70, teacherOnTime: true, sleepIncidents: 1 }),
      session({ date: '2026-09-18', attentionScore: 60, teacherActivityScore: null, teacherOnTime: false }),
      session({ date: '2026-09-19', attentionScore: null, teacher: 'Prof. Karimov Aziz', teacherActivityScore: 90, sleepIncidents: 2 }),
    ]);
    expect(a.sessions).toBe(3);
    expect(a.avgAttention).toBe(70);
    expect(a.avgActivity).toBe(80);
    expect(a.sleepIncidents).toBe(3);
    expect(a.checked).toBe(2);
    expect(a.onTimeRate).toBe(50);
    expect(a.attentionByDay).toEqual([{ date: '2026-09-18', label: '18.09', diqqat: 70, darslar: 2 }]);
    expect(a.activityByTeacher.map((t) => t.teacher)).toEqual(['Karimov Aziz', 'Aliyev Vali']);
  });

  it('returns nulls for an empty period', () => {
    const a = analyzeLessonSessions([]);
    expect(a.avgAttention).toBeNull();
    expect(a.onTimeRate).toBeNull();
  });
});

describe('helpers', () => {
  it('isLessonTracked needs teacher, room and start time', () => {
    expect(isLessonTracked({ teacherId: 'x', room: 'Kamera 1', startsAt: '08:30' })).toBe(true);
    expect(isLessonTracked({ teacherId: null, room: 'Kamera 1', startsAt: '08:30' })).toBe(false);
    expect(isLessonTracked({ teacherId: 'x', room: null, startsAt: '08:30' })).toBe(false);
  });

  it('matchesName ignores case, word order and apostrophe variants', () => {
    expect(matchesName("To'xtayev Ali", 'ali to‘xta')).toBe(true);
    expect(matchesName('Aliyev Vali', 'karim')).toBe(false);
    expect(matchesName('Aliyev Vali', '  ')).toBe(true);
  });

  it('hhmm trims seconds and handles null', () => {
    expect(hhmm('08:05:12')).toBe('08:05');
    expect(hhmm(null)).toBe('—');
  });
});

describe('getLessonSessionsInRange', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('stops paging once records older than the range appear', async () => {
    const pages = [
      { items: [session({ id: 'a', date: '2026-09-20' }), session({ id: 'b', date: '2026-09-19' })], total: 4, page: 1, pageSize: 2, totalPages: 3 },
      { items: [session({ id: 'c', date: '2026-09-18' }), session({ id: 'd', date: '2026-09-10' })], total: 4, page: 2, pageSize: 2, totalPages: 3 },
    ];
    const fetchMock = vi.fn(async (url: string) => {
      const page = Number(new URL(url, 'http://x').searchParams.get('page'));
      return new Response(JSON.stringify(pages[page - 1]), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const out = await getLessonSessionsInRange('2026-09-15', '2026-09-19');
    expect(out.map((s) => s.id)).toEqual(['b', 'c']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
