import { describe, expect, it } from 'vitest';
import { buildId, entryScript, serviceWorkerUrl, shouldRegisterServiceWorker } from './pwa';

describe('serviceWorkerUrl', () => {
  it('build identifikatorini manzilga qo\'shadi', () => {
    expect(serviceWorkerUrl('abc1234')).toBe('/sw.js?v=abc1234');
  });

  it('maxsus belgilarni kodlaydi', () => {
    expect(serviceWorkerUrl('2026-09-19T10:00:00.000Z')).toBe('/sw.js?v=2026-09-19T10%3A00%3A00.000Z');
  });

  it('testlarda (define yo\'q) dev versiyasini ishlatadi', () => {
    expect(buildId()).toBe('dev');
    expect(serviceWorkerUrl()).toBe('/sw.js?v=dev');
  });
});

describe('shouldRegisterServiceWorker', () => {
  const ok = { production: true, secureContext: true, supported: true };

  it('production, HTTPS va qo\'llab-quvvatlansa — ha', () => {
    expect(shouldRegisterServiceWorker(ok)).toBe(true);
  });

  it('dev rejimida — yo\'q', () => {
    expect(shouldRegisterServiceWorker({ ...ok, production: false })).toBe(false);
  });

  it('HTTP (xavfsiz bo\'lmagan kontekst) — yo\'q', () => {
    expect(shouldRegisterServiceWorker({ ...ok, secureContext: false })).toBe(false);
  });

  it('brauzer qo\'llab-quvvatlamasa — yo\'q', () => {
    expect(shouldRegisterServiceWorker({ ...ok, supported: false })).toBe(false);
  });
});

describe('entryScript', () => {
  it('index.html dan asosiy skript nomini oladi (yangi versiyani aniqlash)', () => {
    expect(entryScript('<script type="module" crossorigin src="/app/index-BmaYk3B2.js"></script>')).toBe('/app/index-BmaYk3B2.js');
    expect(entryScript('<html></html>')).toBeNull();
  });
});
