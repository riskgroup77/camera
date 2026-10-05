import { describe, expect, it } from 'vitest';
import {
  DEVICE_STATUS_META,
  EMPTY_DEVICE_FORM,
  RUN_STATUS_META,
  buildDevicePayload,
  deviceToForm,
  formatDateTime,
  formatDuration,
  peopleSearchLink,
  progressPercent,
  statsRows,
  statsSummary,
  validateDeviceForm,
  webhookUrl,
  type AccessDevice,
  type EntityStats,
} from './integrationsApi';

const zero: EntityStats = { fetched: 0, created: 0, updated: 0, unchanged: 0, deactivated: 0, skipped: 0, errors: 0 };

describe('formatDateTime', () => {
  it('server vaqtini brauzer mintaqasiga o\'girmaydi', () => {
    expect(formatDateTime('2026-09-19T08:10:05+05:00')).toBe('19.09.2026 08:10');
    expect(formatDateTime('2026-09-19T08:10:05+05:00', true)).toBe('19.09.2026 08:10:05');
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('noto\'g\'ri')).toBe('noto\'g\'ri');
  });
});

describe('formatDuration', () => {
  it('soniya, daqiqa va soatni ko\'rsatadi', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(42)).toBe('42 s');
    expect(formatDuration(125)).toBe('2 daq 5 s');
    expect(formatDuration(120)).toBe('2 daq');
    expect(formatDuration(3720)).toBe('1 soat 2 daq');
  });
});

describe('stats', () => {
  const stats = {
    students: { ...zero, fetched: 10, created: 2, updated: 3, deactivated: 1 },
    employees: { ...zero, fetched: 4, unchanged: 4 },
    groups: { ...zero },
    progress: { stage: 'Talabalar: yozilmoqda', done: 50, total: 200 },
  };

  it('statsRows faqat faol bo\'limlarni tartib bilan qaytaradi', () => {
    expect(statsRows(stats).map((r) => r.label)).toEqual(['Talabalar', 'Xodimlar']);
    expect(statsRows(null)).toEqual([]);
  });

  it('statsSummary qisqa xulosa beradi', () => {
    expect(statsSummary(stats)).toBe('Talabalar: +2, ~3, −1');
    expect(statsSummary({ employees: { ...zero, unchanged: 5 } })).toBe("O'zgarish yo'q");
  });

  it('progressPercent', () => {
    expect(progressPercent(stats.progress)).toBe(25);
    expect(progressPercent({ stage: 'x', done: 0, total: 0 })).toBeNull();
    expect(progressPercent({ stage: 'x', done: 9, total: 3 })).toBe(100);
    expect(progressPercent(undefined)).toBeNull();
  });
});

describe('webhookUrl', () => {
  it('API manzili bo\'lsa undan, bo\'lmasa sahifa manzilidan', () => {
    expect(webhookUrl('/api/access/webhook/1', 'https://api.example.uz/')).toBe('https://api.example.uz/api/access/webhook/1');
    expect(webhookUrl('api/access/webhook/1', '', 'https://cam.example.uz')).toBe('https://cam.example.uz/api/access/webhook/1');
  });
});

describe('device form', () => {
  it('hikvision uchun IP, login va (yangi qurilmada) parol majburiy', () => {
    const errors = validateDeviceForm({ ...EMPTY_DEVICE_FORM, name: 'T' }, false);
    expect(Object.keys(errors).sort()).toEqual(['ip', 'password', 'username']);
    const editErrors = validateDeviceForm({ ...EMPTY_DEVICE_FORM, name: 'T', ip: '1.2.3.4', username: 'a' }, true);
    expect(editErrors).toEqual({});
    expect(validateDeviceForm({ ...EMPTY_DEVICE_FORM, kind: 'webhook', name: 'W', port: '70000' }, false)).toEqual({
      port: "Port 1–65535 oralig'ida",
    });
  });

  it('payload: tahrirlashda bo\'sh parol va tur yuborilmaydi', () => {
    const form = { ...EMPTY_DEVICE_FORM, name: ' Hik ', ip: '10.0.0.1', username: 'admin', password: '' };
    const edit = buildDevicePayload(form, true);
    expect(edit).not.toHaveProperty('password');
    expect(edit).not.toHaveProperty('kind');
    expect(edit.name).toBe('Hik');
    expect(edit.port).toBe(80);
    const create = buildDevicePayload({ ...form, password: 'pw', port: '' }, false);
    expect(create.kind).toBe('hikvision');
    expect(create.password).toBe('pw');
    expect(create.port).toBeNull();
  });

  it('deviceToForm parolni hech qachon to\'ldirmaydi', () => {
    const device: AccessDevice = {
      id: '1', name: 'D', kind: 'webhook', ip: null, port: null, username: null, hasPassword: true, hasApiKey: true,
      direction: 'chiqish', buildingId: null, buildingName: null, marksAttendance: false, enabled: true,
      status: 'onlayn', lastEventAt: null, lastPollAt: null, lastError: null, webhookPath: '/api/access/webhook/1',
      createdAt: null,
    };
    const form = deviceToForm(device);
    expect(form.password).toBe('');
    expect(form.direction).toBe('chiqish');
    expect(form.marksAttendance).toBe(false);
  });
});

describe('status meta', () => {
  it('dizayn tizimi ohanglaridan foydalanadi', () => {
    expect(DEVICE_STATUS_META.onlayn.tone).toBe('success');
    expect(DEVICE_STATUS_META.xato.tone).toBe('danger');
    expect(RUN_STATUS_META.muvaffaqiyatli.tone).toBe('success');
    expect(RUN_STATUS_META.ishlamoqda.tone).toBe('info');
  });
});

describe('peopleSearchLink', () => {
  it('qidiruv parametrini kodlaydi', () => {
    expect(peopleSearchLink('00 12')).toBe('/reestr?search=00+12');
    expect(peopleSearchLink('Ali Valiyev')).toBe('/reestr?search=Ali+Valiyev');
  });
});

/**
 * QA: Hikvision qurilmasining IP manzili shakl bo'yicha tekshirilmasdi —
 * "kamera-1" yoki "192.168.1" ham saqlanardi (backend uni oddiy satr deb
 * qabul qiladi). Qurilma keyin abadiy "xato" holatida turib qolardi va
 * admin sababini tushunmasdi.
 */
describe('validateDeviceForm — IP manzil shakli', () => {
  const hik = { ...EMPTY_DEVICE_FORM, name: 'Kirish', kind: 'hikvision' as const, username: 'admin', password: 'x' };

  it("to'g'ri IP qabul qilinadi", () => {
    expect(validateDeviceForm({ ...hik, ip: '192.168.1.50' }, false).ip).toBeUndefined();
  });

  it("noto'g'ri IP rad etiladi", () => {
    expect(validateDeviceForm({ ...hik, ip: 'kamera-1' }, false).ip).toBeTruthy();
    expect(validateDeviceForm({ ...hik, ip: '192.168.1' }, false).ip).toBeTruthy();
    expect(validateDeviceForm({ ...hik, ip: '999.1.1.1' }, false).ip).toBeTruthy();
  });

  it("bo'sh IP uchun xabar «kiriting» bo'lib qoladi", () => {
    expect(validateDeviceForm({ ...hik, ip: '' }, false).ip).toBe('IP manzilni kiriting');
  });

  it('webhook qurilmasida IP talab qilinmaydi', () => {
    expect(validateDeviceForm({ ...EMPTY_DEVICE_FORM, name: 'W', kind: 'webhook', ip: '' }, false).ip).toBeUndefined();
  });
});
