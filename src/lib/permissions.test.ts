import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ReactNode } from 'react';

// Force the demo/local-storage code path regardless of this dev machine's
// .env.local (which points at a real backend) — these tests exercise the
// pure client-side matrix logic in isolation; the real-backend path is
// verified live against camera-api (see UsersRolesPage browser walkthrough).
vi.mock('./config', () => ({ isBackendConfigured: false, config: { apiBaseUrl: '', realtimeUrl: '', streamGatewayUrl: '' } }));

const { usePermissions, PermissionsProvider } = await import('./permissions');
const { AuthProvider } = await import('./auth');

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AuthProvider, null, createElement(PermissionsProvider, null, children));
}

describe('usePermissions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('denies access when there is no role', () => {
    const { result } = renderHook(() => usePermissions(), { wrapper });
    expect(result.current.can('manageCameras', null)).toBe(false);
  });

  it('reflects the default matrix for each role', () => {
    const { result } = renderHook(() => usePermissions(), { wrapper });
    expect(result.current.can('systemSettings', 'super-admin')).toBe(true);
    expect(result.current.can('systemSettings', 'admin')).toBe(false);
    expect(result.current.can('manageCameras', 'admin')).toBe(true);
  });

  it('toggle() flips the admin permission and can() reflects it immediately', () => {
    const { result } = renderHook(() => usePermissions(), { wrapper });

    expect(result.current.can('manageRoles', 'admin')).toBe(false);

    act(() => {
      result.current.toggle('manageRoles', 'admin');
    });

    expect(result.current.can('manageRoles', 'admin')).toBe(true);
  });

  it('toggle() never affects the other role', () => {
    const { result } = renderHook(() => usePermissions(), { wrapper });

    act(() => {
      result.current.toggle('manageRoles', 'admin');
    });

    expect(result.current.can('manageRoles', 'super-admin')).toBe(true);
  });
});
