import { describe, expect, it } from 'vitest';
import type { AccessDevice } from './integrationsApi';
import {
  deviceLastContact,
  isLiveDay,
  onlineSummary,
  passDirectionLabel,
  passPerson,
  passQuery,
  passResult,
  passTime,
  sortDevices,
} from './accessPage';

const device = (over: Partial<AccessDevice>): AccessDevice => ({
  id: 'd',
  name: 'Turniket',
  kind: 'hikvision',
  ip: '10.0.0.5',
  port: 80,
  username: 'admin',
  hasPassword: true,
  hasApiKey: false,
  direction: 'kirish',
  buildingId: null,
  buildingName: null,
  marksAttendance: true,
  enabled: true,
  status: 'onlayn',
  lastEventAt: '2026-09-24T08:00:00+05:00',
  lastPollAt: '2026-09-24T08:10:05+05:00',
  lastError: null,
  webhookPath: null,
  createdAt: null,
  ...over,
});

describe('accessPage helpers', () => {
  it("filtrlar bitta kunlik so'rovga aylanadi", () => {
    expect(passQuery({ deviceId: '', direction: '', date: '2026-09-24' })).toEqual({
      deviceId: undefined,
      direction: undefined,
      from: '2026-09-24',
      to: '2026-09-24',
    });
    expect(passQuery({ deviceId: 'd1', direction: 'chiqish', date: '2026-09-23' })).toMatchObject({
      deviceId: 'd1',
      direction: 'chiqish',
    });
  });

  it('jonli oqim faqat bugun', () => {
    expect(isLiveDay('2026-09-24', '2026-09-24')).toBe(true);
    expect(isLiveDay('2026-09-23', '2026-09-24')).toBe(false);
  });

  it('vaqt, shaxs, yo‘nalish, natija', () => {
    expect(passTime('2026-09-24T08:10:05+05:00')).toBe('08:10:05');
    expect(passTime('2026-09-24T08:10+05:00')).toBe('08:10:00');
    expect(passTime(null)).toBe('—');

    expect(passPerson({ personName: 'Aliyev Vali', cardNumber: '1', employeeNo: null })).toEqual({ label: 'Aliyev Vali', known: true });
    expect(passPerson({ personName: null, cardNumber: '00123', employeeNo: 'E-7' }).label).toBe('Karta 00123');
    expect(passPerson({ personName: null, cardNumber: null, employeeNo: 'E-7' }).label).toBe('ID E-7');
    expect(passPerson({ personName: null, cardNumber: null, employeeNo: null })).toEqual({ label: "Noma'lum", known: false });

    expect(passDirectionLabel('kirish')).toBe('Kirish');
    expect(passDirectionLabel('chiqish')).toBe('Chiqish');
    expect(passDirectionLabel(null)).toBe('—');
    expect(passResult(true).status).toBe('ok');
    expect(passResult(false)).toEqual({ label: 'Rad etildi', status: 'alert' });
  });

  it("qurilma bilan oxirgi aloqa turiga qarab", () => {
    expect(deviceLastContact(device({}))).toEqual({ label: "So'rov", value: '24.09.2026 08:10' });
    expect(deviceLastContact(device({ kind: 'webhook', lastPollAt: null }))).toEqual({ label: 'Hodisa', value: '24.09.2026 08:00' });
    expect(deviceLastContact(device({ kind: 'zkteco', lastEventAt: null })).value).toBe('—');
  });

  it('muammoli qurilmalar yuqorida, onlayn sanog‘i', () => {
    const list = [
      device({ id: '1', name: 'B', status: 'onlayn' }),
      device({ id: '2', name: 'A', status: 'onlayn' }),
      device({ id: '3', name: 'C', status: 'xato' }),
      device({ id: '4', name: 'D', status: 'ochirilgan', enabled: false }),
      device({ id: '5', name: 'E', status: 'oflayn' }),
    ];
    expect(sortDevices(list).map((d) => d.id)).toEqual(['3', '5', '2', '1', '4']);
    expect(onlineSummary(list)).toBe('2/4 onlayn');
    expect(onlineSummary([])).toBe('0/0 onlayn');
  });
});
