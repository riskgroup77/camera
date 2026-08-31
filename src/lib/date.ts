/**
 * `Date.toISOString().slice(0, 10)` looks like an obvious way to get a
 * "YYYY-MM-DD" string, but it converts to UTC first — for a local Date
 * built from local year/month/day (e.g. `new Date(2026, 7, 31)`, midnight
 * local time), that shifts to the PREVIOUS calendar day for any timezone
 * ahead of UTC (Uzbekistan is UTC+5), silently off-by-one. Use this
 * instead whenever the local calendar day matters — e.g. matching a
 * per-day lookup key against a backend date (already the institute's
 * local day, see camera-api's app/timezone.py) or a "today" default.
 */
export function toLocalDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
