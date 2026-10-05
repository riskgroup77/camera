import { describe, expect, it } from 'vitest';
import {
  addMinutes,
  minutesOfDay,
  validateAttendancePolicy,
  type AttendancePolicyInput,
} from './attendancePolicyApi';

/**
 * "Ish vaqti" sahifasi QA: saqlashdan oldingi tekshiruv.
 *
 * Ilgari bu yerda hech qanday tekshiruv yo'q edi — `type="time"` maydoni
 * tozalanishi mumkin (qiymat bo'sh satr bo'ladi), ish kunlarining hammasini
 * o'chirib qo'yish ham mumkin edi. Ikkalasi ham serverga ketib, javobida
 * pydantic'ning inglizcha xatosi qaytardi, yon tarafdagi "Qanday hisoblanadi"
 * kartasi esa "NaN:NaN" ko'rsatardi.
 */

const BASE: AttendancePolicyInput = {
  staffStart: '08:30',
  studentStart: '08:00',
  graceMinutes: 15,
  workEnd: '17:00',
  workDays: [1, 2, 3, 4, 5],
  trackLastSeen: true,
};

describe('addMinutes / minutesOfDay', () => {
  it("to'g'ri vaqtni qo'shadi", () => {
    expect(addMinutes('08:00', 10)).toBe('08:10');
    expect(addMinutes('23:55', 10)).toBe('00:05');
  });

  it("bo'sh yoki noto'g'ri vaqtda NaN emas, «—» qaytaradi", () => {
    expect(addMinutes('', 15)).toBe('—');
    expect(addMinutes('soat', 15)).toBe('—');
    expect(addMinutes('99:99', 15)).toBe('—');
  });

  it('minutesOfDay chegaralarni biladi', () => {
    expect(minutesOfDay('00:00')).toBe(0);
    expect(minutesOfDay('23:59')).toBe(1439);
    expect(minutesOfDay('24:00')).toBeNull();
    expect(minutesOfDay('')).toBeNull();
  });
});

describe('validateAttendancePolicy', () => {
  it("to'g'ri qoidada xato yo'q", () => {
    expect(validateAttendancePolicy(BASE)).toEqual({});
  });

  it("bo'sh vaqt maydonlari xato beradi", () => {
    const errors = validateAttendancePolicy({ ...BASE, staffStart: '', studentStart: '', workEnd: '' });
    expect(errors.staffStart).toBeTruthy();
    expect(errors.studentStart).toBeTruthy();
    expect(errors.workEnd).toBeTruthy();
  });

  it("bo'sh ish kunlari ro'yxati rad etiladi", () => {
    expect(validateAttendancePolicy({ ...BASE, workDays: [] }).workDays).toMatch(/Kamida bitta ish kuni/);
  });

  it("ish tugashi boshlanishidan oldin bo'lsa rad etiladi", () => {
    expect(validateAttendancePolicy({ ...BASE, workEnd: '07:00' }).workEnd).toBeTruthy();
    expect(validateAttendancePolicy({ ...BASE, workEnd: '08:30' }).workEnd).toBeTruthy();
  });

  it('kechikish daqiqasi 0..180 oralig\'ida', () => {
    expect(validateAttendancePolicy({ ...BASE, graceMinutes: -1 }).graceMinutes).toBeTruthy();
    expect(validateAttendancePolicy({ ...BASE, graceMinutes: 181 }).graceMinutes).toBeTruthy();
    expect(validateAttendancePolicy({ ...BASE, graceMinutes: 0 }).graceMinutes).toBeUndefined();
    expect(validateAttendancePolicy({ ...BASE, graceMinutes: 180 }).graceMinutes).toBeUndefined();
  });
});

describe('kechikish chegarasi ish tugashidan oshib ketmasin', () => {
  it("16:00 + 120 daqiqa 17:00 dan oshadi — xato", () => {
    const errors = validateAttendancePolicy({
      ...BASE,
      staffStart: '16:00',
      studentStart: '16:00',
      graceMinutes: 120,
      workEnd: '17:00',
    });
    expect(errors.graceMinutes).toMatch(/kech kelgan hisoblanmaydi/);
  });

  it("odatiy qoidada bu xato chiqmaydi", () => {
    expect(validateAttendancePolicy(BASE).graceMinutes).toBeUndefined();
  });

  it("180 dan katta qiymat ham xato beradi", () => {
    expect(validateAttendancePolicy({ ...BASE, graceMinutes: 200 }).graceMinutes).toMatch(/0 dan 180 gacha/);
  });
});
