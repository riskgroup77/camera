import { describe, expect, it } from 'vitest';
import { QUEUE_STATUSES, eventQueryParams, type EventFilters } from './eventQuery';

const base: EventFilters = {
  queue: false,
  severity: '',
  statusFilter: '',
  quick: '',
  moduleCode: '',
  building: '',
  from: '',
  to: '',
  search: '',
};

describe('eventQueryParams', () => {
  it('"tayinlanmagan" tezkor filtri ochiq holatlar bilan cheklaydi (eksport ham shu bilan)', () => {
    const params = eventQueryParams({ ...base, quick: 'tayinlanmagan' });
    expect(params.assignedTo).toBe('none');
    // Bu cheklov eksportda tushib qolgan edi: yopilgan hodisalar ham faylga tushardi.
    expect(params.status).toBe(QUEUE_STATUSES);
  });

  it('aniq tanlangan holat tezkor filtrdan ustun turadi', () => {
    const params = eventQueryParams({ ...base, quick: 'tayinlanmagan', statusFilter: 'hal_qilindi' });
    expect(params.status).toBe('hal_qilindi');
  });

  it('navbat ko\'rinishi doim yangi/jarayonda', () => {
    expect(eventQueryParams({ ...base, queue: true, statusFilter: 'rad_etilgan' }).status).toBe(QUEUE_STATUSES);
  });

  it('boshqa filtrlar va qidiruv uzatiladi, bo\'shlari yo\'q', () => {
    const params = eventQueryParams({
      ...base,
      severity: 'yuqori',
      quick: 'muddati',
      moduleCode: '12',
      building: 'A',
      from: '2026-01-01',
      to: '2026-01-31',
      search: '  kamera  ',
    });
    expect(params).toMatchObject({
      severity: 'yuqori',
      overdue: 'true',
      moduleCodes: '12',
      building: 'A',
      from: '2026-01-01',
      to: '2026-01-31',
      search: 'kamera',
    });
    expect(params.assignedTo).toBeUndefined();
    expect(params.status).toBeUndefined();
  });

  it('"mening" — menga tayinlangan, holat cheklovisiz', () => {
    const params = eventQueryParams({ ...base, quick: 'mening' });
    expect(params.assignedTo).toBe('me');
    expect(params.status).toBeUndefined();
  });
});
