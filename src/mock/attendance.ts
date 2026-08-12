import type { AttendanceDay, AttendanceDayStatus } from '../types';

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export function getMonthAttendance(
  personId: string,
  year: number,
  month: number, // 0-indexed
): AttendanceDay[] {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const days: AttendanceDay[] = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d);
    const iso = date.toISOString().slice(0, 10);
    const dow = date.getDay();

    if (date > today) {
      days.push({ date: iso, status: 'dam_olish' as AttendanceDayStatus });
      continue;
    }

    if (dow === 0 || dow === 6) {
      days.push({ date: iso, status: 'dam_olish' });
      continue;
    }

    const seed = hashString(`${personId}-${iso}`) % 20;
    let status: AttendanceDayStatus;
    if (seed < 16) status = 'keldi';
    else if (seed < 18) status = 'kech_keldi';
    else status = 'kelmadi';

    days.push({
      date: iso,
      status,
      checkIn: status !== 'kelmadi' ? (status === 'kech_keldi' ? '09:1' + (seed % 9) : '08:5' + (seed % 9)) : undefined,
      checkOut: status !== 'kelmadi' ? '17:0' + (seed % 9) : undefined,
    });
  }

  return days;
}

export function isFutureDate(iso: string): boolean {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return new Date(iso) > today;
}
