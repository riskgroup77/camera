import { describe, expect, it } from 'vitest';
import { syncServerPageCacheOwner } from './useServerPage';

describe('syncServerPageCacheOwner', () => {
  it("birinchi token — kesh egasi belgilanadi", () => {
    expect(syncServerPageCacheOwner('token-a')).toBe(true);
  });

  it("o'sha token — kesh saqlanadi", () => {
    syncServerPageCacheOwner('token-a');
    expect(syncServerPageCacheOwner('token-a')).toBe(false);
    expect(syncServerPageCacheOwner('token-a')).toBe(false);
  });

  it('boshqa foydalanuvchi kirsa kesh tozalanadi', () => {
    syncServerPageCacheOwner('token-a');
    expect(syncServerPageCacheOwner('token-b')).toBe(true);
    expect(syncServerPageCacheOwner('token-b')).toBe(false);
  });

  it('chiqish (null) ham keshni tozalaydi', () => {
    syncServerPageCacheOwner('token-a');
    expect(syncServerPageCacheOwner(null)).toBe(true);
    expect(syncServerPageCacheOwner(null)).toBe(false);
    expect(syncServerPageCacheOwner('token-a')).toBe(true);
  });
});
