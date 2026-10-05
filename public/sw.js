/* Nazorat — service worker (src/lib/pwa.ts ro'yxatdan o'tkazadi).
 *
 * Nima qiladi:
 *   - sahifalar (navigatsiya): avval tarmoq, tarmoq bo'lmasa oxirgi
 *     saqlangan ilova qobig'i (index.html) — yangi deploy darhol ko'rinadi;
 *   - /app/* va /assets/* (Vite, nomida hash bor): keshdan, bo'lmasa tarmoqdan;
 *   - ikonlar, shriftlar, manifest: keshdan darhol, fonda yangilanadi.
 *
 * Nima QILMAYDI (ataylab): /api, WebSocket, jonli video (HLS: /s0/.., /cam-..,
 * .m3u8/.ts/.m4s), Grafana, boshqa domenlar (camapi, storage, stream) va
 * GET bo'lmagan so'rovlar — ular to'g'ridan-to'g'ri tarmoqqa ketadi. Shaxsiy
 * ma'lumot va jonli tasvir hech qachon keshga tushmaydi.
 *
 * Versiya ro'yxatdan o'tkazish manzilidan olinadi (/sw.js?v=<build>): yangi
 * build — yangi service worker, eski qobiq keshlari o'chiriladi.
 */

const VERSION = new URL(self.location.href).searchParams.get('v') || 'dev';
const PREFIX = 'sm-';
const SHELL_CACHE = `${PREFIX}shell-${VERSION}`;
const STATIC_CACHE = `${PREFIX}static-${VERSION}`;
// Hashli fayllar versiyalar orasida saqlanadi: eski ochiq sahifa yangi deploydan
// keyin ham o'z bo'laklarini (lazy chunk) yuklay olsin. Hajm cheklangan.
const ASSETS_CACHE = `${PREFIX}assets`;
const ASSETS_MAX_ENTRIES = 300;
const SHELL_URL = '/index.html';

const PRECACHE = [
  SHELL_URL,
  '/manifest.webmanifest',
  '/favicon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

const BYPASS_PREFIXES = ['/api/', '/ws', '/grafana', '/cam-', '/storage/', '/metrics'];
const STREAM_PATH = /^\/s\d+\//;
const MEDIA_EXT = /\.(m3u8|ts|m4s|mp4|m4a|aac|webm)$/i;
const STATIC_EXT = /\.(png|svg|ico|webp|jpg|jpeg|woff2?|ttf|webmanifest)$/i;

function isBypassed(url, request) {
  if (url.origin !== self.location.origin) return true;
  if (request.method !== 'GET') return true;
  if (request.headers.has('range')) return true;
  if (url.pathname === '/sw.js') return true;
  if (BYPASS_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return true;
  if (STREAM_PATH.test(url.pathname) || MEDIA_EXT.test(url.pathname)) return true;
  return false;
}

function isCacheable(response) {
  return response && response.ok && response.type === 'basic';
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((path) => new Request(path, { cache: 'reload' }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(PREFIX) && key !== ASSETS_CACHE && key !== SHELL_CACHE && key !== STATIC_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

async function trimAssets() {
  const cache = await caches.open(ASSETS_CACHE);
  const keys = await cache.keys();
  const excess = keys.length - ASSETS_MAX_ENTRIES;
  for (let i = 0; i < excess; i += 1) {
    await cache.delete(keys[i]);
  }
}

async function handleNavigation(request) {
  try {
    const response = await fetch(request);
    const type = response.headers.get('content-type') || '';
    if (isCacheable(response) && type.includes('text/html')) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put(SHELL_URL, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(SHELL_URL);
    if (cached) return cached;
    return new Response(
      '<!doctype html><html lang="uz"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' +
        '<title>Nazorat</title><body style="font-family:system-ui,sans-serif;background:#E8EDFF;color:#0F172A;' +
        'display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;text-align:center">' +
        '<div><h1 style="font-size:20px">Tarmoq bilan aloqa yo\'q</h1>' +
        '<p>Internet yoki institut tarmog\'iga ulanishni tekshirib, sahifani yangilang.</p></div></body></html>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
    );
  }
}

async function handleAsset(request) {
  const cache = await caches.open(ASSETS_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (isCacheable(response)) {
    await cache.put(request, response.clone());
    trimAssets().catch(() => undefined);
  }
  return response;
}

async function handleStatic(request, event) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then(async (response) => {
      if (isCacheable(response)) await cache.put(request, response.clone());
      return response;
    })
    .catch(() => undefined);
  if (cached) {
    event.waitUntil(network);
    return cached;
  }
  const response = await network;
  if (response) return response;
  const precached = await caches.match(request);
  return precached || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (isBypassed(url, request)) return;

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request));
    return;
  }
  // Build --assetsDir app bilan chiqadi (/app/*); /assets/* eski build uchun.
  if (url.pathname.startsWith('/app/') || url.pathname.startsWith('/assets/')) {
    event.respondWith(handleAsset(request));
    return;
  }
  if (STATIC_EXT.test(url.pathname)) {
    event.respondWith(handleStatic(request, event));
  }
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});
