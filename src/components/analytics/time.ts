/** Daqiqa <-> "08:24" o'giruvchilar. */
export function minutesToClock(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const m = Math.round(value);
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

/** "08:24" → 504. */
export function clockToMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const [h, m] = value.split(':').map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
}
