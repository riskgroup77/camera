import { afterEach, describe, expect, it, vi } from 'vitest';
import { cachedRequest, clearResponseCache, ttlForDate } from './responseCache';

afterEach(() => clearResponseCache());

describe('responseCache', () => {
  it('TTL ichida bitta so‘rov; bekor qilish faqat chaqiruvchini to‘xtatadi', async () => {
    const load = vi.fn(async () => 'guruhlar');
    const controller = new AbortController();
    const aborted = cachedRequest('/groups?date=2026-10-05', 60_000, load, controller.signal);
    controller.abort();
    await expect(aborted).rejects.toMatchObject({ name: 'AbortError' });
    // Oldindan yuklangan / bekor qilingan so'rov baribir keshda.
    await expect(cachedRequest('/groups?date=2026-10-05', 60_000, load)).resolves.toBe('guruhlar');
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('xato keshda qolmaydi', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('tarmoq')).mockResolvedValueOnce('ok');
    await expect(cachedRequest('/x', 60_000, load)).rejects.toThrow('tarmoq');
    await expect(cachedRequest('/x', 60_000, load)).resolves.toBe('ok');
  });

  it('o‘tgan kun uzoqroq, bugun qisqa keshlanadi', () => {
    expect(ttlForDate('2026-10-05', '2026-10-06')).toBe(300_000);
    expect(ttlForDate('2026-10-06', '2026-10-06')).toBe(15_000);
  });
});
