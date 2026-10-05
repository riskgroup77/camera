import { describe, expect, it } from 'vitest';
import { clockOf, etaMinutes, isRunActive, lessonsSummary, runProgressText, teacherSummary, type AnalysisRun } from './videoAnalysisApi';
import { EMPTY_NVR_FORM, buildNvrPayload, nvrToForm, validateNvrForm } from './nvrForm';

const RUN: AnalysisRun = {
  id: 'r1',
  day: '2026-10-05',
  status: 'ishlamoqda',
  windowStart: '2026-10-05T07:00:00+05:00',
  windowEnd: '2026-10-05T20:00:00+05:00',
  createdAt: null,
  startedAt: '2026-10-05T20:00:00+05:00',
  finishedAt: null,
  jobsTotal: 120,
  jobsDone: 30,
  jobsFailed: 4,
  jobsNoVideo: 2,
  framesPlanned: 100_000,
  framesAnalyzed: 25_000,
  facesDetected: 9000,
  observations: 4000,
  progress: 0.28,
  stats: null,
  error: null,
  triggeredBy: 'tizim',
};

describe('kunlik tahlil yordamchilari', () => {
  it('vaqtni ISO dan oladi', () => {
    expect(clockOf('2026-10-05T08:12:44+05:00')).toBe('08:12');
    expect(clockOf(null)).toBe('—');
    expect(clockOf('buzuq')).toBe('—');
  });

  it("darslar katagi o'lchanmaganini ajratadi", () => {
    const base = { lessonsTotal: 4, lessonsAttended: 2, lessonsLate: 1, lessonsLeftEarly: 0, lessonsUnmeasured: 1 };
    expect(lessonsSummary(base)).toBe('2/3 · 1 kech');
    expect(lessonsSummary({ ...base, lessonsUnmeasured: 4 })).toBe('o‘lchanmadi');
    expect(lessonsSummary({ ...base, lessonsTotal: null })).toBe('—');
    expect(lessonsSummary({ ...base, lessonsLeftEarly: 2, lessonsLate: 0 })).toBe('2/3 · 2 erta');
  });

  it("o'qituvchi katagi", () => {
    expect(teacherSummary({ teacherLessons: 3, teacherOnTime: 1, teacherLate: 1, teacherAbsent: 1 })).toBe('1/3 vaqtida · 1 kech · 1 kelmadi');
    expect(teacherSummary({ teacherLessons: null, teacherOnTime: null, teacherLate: null, teacherAbsent: null })).toBe('—');
  });

  it('jarayon matni va qolgan vaqt', () => {
    expect(runProgressText(RUN)).toBe(`34 / 120 vazifa · ${(25000).toLocaleString('ru-RU')} kadr`);
    // 25 000 kadr 50 daqiqada -> 500/daq; qolgan 75 000 -> 150 daq.
    const now = Date.parse('2026-10-05T20:50:00+05:00');
    expect(etaMinutes(RUN, now)).toBe(150);
    expect(etaMinutes({ ...RUN, framesAnalyzed: 0 }, now)).toBeNull();
    expect(etaMinutes({ ...RUN, startedAt: null }, now)).toBeNull();
  });

  it('faol holatlar', () => {
    expect(isRunActive(RUN)).toBe(true);
    expect(isRunActive({ ...RUN, status: 'agregatsiya' })).toBe(true);
    expect(isRunActive({ ...RUN, status: 'tugadi' })).toBe(false);
    expect(isRunActive(null)).toBe(false);
  });
});

describe('NVR formasi', () => {
  it("bo'sh forma xatolari", () => {
    const errors = validateNvrForm({ ...EMPTY_NVR_FORM });
    expect(errors.name).toBeTruthy();
    expect(errors.ip).toBeTruthy();
    expect(validateNvrForm({ ...EMPTY_NVR_FORM, name: 'N', ip: '192.168.0.300' }).ip).toBeTruthy();
    expect(validateNvrForm({ ...EMPTY_NVR_FORM, name: 'N', ip: '192.168.0.94', httpPort: '70000' }).httpPort).toBeTruthy();
    expect(validateNvrForm({ ...EMPTY_NVR_FORM, name: 'N', ip: 'nvr.local', maxStreams: '0' }).maxStreams).toBeTruthy();
    expect(validateNvrForm({ ...EMPTY_NVR_FORM, name: 'N', ip: '192.168.0.94' })).toEqual({});
    expect(validateNvrForm({ ...EMPTY_NVR_FORM, name: 'N', kind: 'fayl' }).basePath).toBeTruthy();
  });

  it("tahrirlashda bo'sh parol yuborilmaydi", () => {
    const form = { ...EMPTY_NVR_FORM, name: ' NVR ', ip: ' 10.0.0.5 ' };
    expect(buildNvrPayload(form, true)).not.toHaveProperty('password');
    expect(buildNvrPayload({ ...form, password: 'x' }, true).password).toBe('x');
    const created = buildNvrPayload(form, false);
    expect(created).toMatchObject({ name: 'NVR', ip: '10.0.0.5', httpPort: 80, rtspPort: 554, fetchMode: 'download', password: null });
  });

  it("papka turida tarmoq maydonlari yuborilmaydi", () => {
    const payload = buildNvrPayload({ ...EMPTY_NVR_FORM, name: 'E', kind: 'fayl', basePath: ' /data ' }, false);
    expect(payload).toEqual({ name: 'E', kind: 'fayl', maxStreams: 8, enabled: true, basePath: '/data' });
  });

  it("serverdagi NVR formaga o'tadi (parolsiz)", () => {
    const form = nvrToForm({
      id: '1', name: 'N', kind: 'hikvision', ip: '1.2.3.4', httpPort: 8080, rtspPort: 554, username: 'admin',
      hasPassword: true, stream: 'sub', fetchMode: 'rtsp', maxStreams: 4, localTime: false,
      rtspPathTemplate: '', basePath: null, enabled: true, lastCheckAt: null, lastError: null, channelCount: null, cameras: 2,
    });
    expect(form).toMatchObject({ httpPort: '8080', password: '', stream: 'sub', fetchMode: 'rtsp', localTime: false });
  });
});
