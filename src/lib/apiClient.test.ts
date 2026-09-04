import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, setAuthTokenGetter, setUnauthorizedHandler } from './apiClient';

/**
 * The token used to be threaded by hand into every call —
 * api.get(path, token). Admin pages always passed it; the monitoring
 * wall never did, because /api/public/* was an open surface. The moment
 * those endpoints started requiring auth, every one of the wall's calls
 * came back 401 and the page drew an empty list without an error:
 * "no cameras connected", on a system where all 107 were online.
 *
 * These tests pin the fix — one place decides the header — so a new
 * call site cannot reintroduce it by simply forgetting an argument.
 */
describe('apiClient auth token', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  function lastHeaders(): Record<string, string> {
    return (fetchMock.mock.calls.at(-1)?.[1]?.headers ?? {}) as Record<string, string>;
  }

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    setAuthTokenGetter(null);
    setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
  });

  it('attaches the session token without the caller passing it', async () => {
    setAuthTokenGetter(() => 'session-token');
    await api.get('/api/public/cameras');
    expect(lastHeaders().Authorization).toBe('Bearer session-token');
  });

  it('sends no Authorization header when nobody is logged in', async () => {
    setAuthTokenGetter(() => null);
    await api.get('/api/public/enrollment/whatever');
    expect(lastHeaders().Authorization).toBeUndefined();
  });

  it('lets an explicitly passed token win over the session one', async () => {
    setAuthTokenGetter(() => 'session-token');
    await api.get('/api/something', 'explicit-token');
    expect(lastHeaders().Authorization).toBe('Bearer explicit-token');
  });

  it('a getter registered during render is used by requests fired from child effects', async () => {
    // React runs child effects BEFORE parent ones. When auth.tsx
    // registered this getter in an effect, the monitoring page had
    // already fired its first request without a token and rendered
    // "could not load cameras" — every fresh page load, on a perfectly
    // valid session. Registration happens during render now; this pins
    // that the getter works the moment it is set, with no mount step in
    // between.
    setAuthTokenGetter(() => 'render-time-token');
    await api.get('/api/public/cameras');
    expect(lastHeaders().Authorization).toBe('Bearer render-time-token');
  });

  it('reads the token at call time, not at registration time', async () => {
    let current: string | null = null;
    setAuthTokenGetter(() => current);
    current = 'token-after-login';
    await api.get('/api/public/stats');
    expect(lastHeaders().Authorization).toBe('Bearer token-after-login');
  });

  it('treats a 401 on a session-token request as an expired session', async () => {
    const onUnauthorized = vi.fn();
    setAuthTokenGetter(() => 'session-token');
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 401 }));

    await expect(api.get('/api/public/cameras')).rejects.toThrow();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it('does not treat a 401 without any token as an expired session', async () => {
    // A failed login is a 401 too; reacting to it would send the login
    // page into a loop of logging itself out.
    const onUnauthorized = vi.fn();
    setAuthTokenGetter(() => null);
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 401 }));

    await expect(api.post('/api/auth/login', {})).rejects.toThrow();
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});
