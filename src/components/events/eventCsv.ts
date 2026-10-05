import { STATUS_LABEL } from '../../lib/eventLabels';
import { cameraLabel } from './ReviewCard';
import type { AIEvent } from '../../types';

/**
 * Hodisalar jurnalining CSV eksporti — sarlavhalar, qator yasash va fayl
 * nomi bitta joyda (sahifadan ajratilgani testga ham qulay).
 *
 * Kadr havolalari (shaxsiy ma'lumot) faylga TUSHMAYDI.
 */
export const EVENT_CSV_HEADERS = [
  'Vaqt',
  'Kriteriya',
  'Kamera',
  'Bino',
  'Shaxs',
  'Ishonch %',
  'Muhimlik',
  'Holat',
  "Mas'ul",
  'Muddat',
  "Ko'rib chiqdi",
  'Yechim',
] as const;

/** ISO vaqtni jadvalda o'qiladigan "YYYY-MM-DD HH:MM" ko'rinishiga keltiradi.
 *
 *  Ilgari `dueAt` faylga xom ISO (`2026-09-20T12:00:00Z`) bo'lib tushardi,
 *  «Vaqt» ustuni esa allaqachon odam o'qiydigan ko'rinishda edi — bitta
 *  faylda ikki xil format, Excel esa `T`/`Z` li satrni sana deb tanimaydi.
 *  Ekrandagi SlaBadge ham aynan shu kesishdan foydalanadi. */
export function csvDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

export function eventCsvRow(event: AIEvent): (string | number)[] {
  return [
    event.timestamp,
    `№${event.moduleCode} ${event.moduleName}`,
    cameraLabel(event),
    event.building ?? '',
    event.personName ?? '',
    event.confidence,
    event.severity,
    STATUS_LABEL[event.status] ?? event.status,
    event.assignedToName ?? '',
    csvDateTime(event.dueAt),
    event.reviewedBy ?? '',
    event.resolutionNote ?? '',
  ];
}

/** Fayl nomida soat ham bor: bir kunda bir necha marta (turli filtr bilan)
 *  eksport qilinganda fayllar "hodisalar-2026-09-20.csv" bo'lib ustma-ust
 *  tushmasin va qaysi biri qachon olingani ko'rinib tursin. */
export function eventsCsvFilename(date: string, now: Date = new Date()): string {
  const time = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tashkent',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
    .format(now)
    .replace(':', '-');
  return `hodisalar-${date}-${time}.csv`;
}
