// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * QA: foydalanuvchilar va huquqlar sahifasi.
 *
 *  - Server rad etadigan o'chirishlar (o'zini o'zi; Super Admin hisobini
 *    oddiy admin) endi bosiladigan tugma sifatida turmaydi — sababi
 *    yorliqda yozilgan (ilgari 400/403 xatosi bilan tugardi).
 *  - Super Admin ustuni qulfi sababi bilan ko'rsatiladi.
 */

const USERS = [
  { id: 'u1', name: 'Men O‘zim', login: 'men', role: 'Admin', lastLogin: '2026-01-01 10:00', email: null, phone: null, telegramLinked: false, twoFactorEnabled: true, allowedBuildingIds: ['b1', 'b2'] },
  { id: 'u2', name: 'Bosh Admin', login: 'bosh', role: 'Super Admin', lastLogin: '2026-01-01 10:00', email: null, phone: null, telegramLinked: false },
  { id: 'u3', name: 'Oddiy Xodim', login: 'xodim', role: "Kamera mas'uli", lastLogin: '2026-01-01 10:00', email: null, phone: null, telegramLinked: false },
];

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'admin', userName: 'Men O‘zim' }) }));
vi.mock('../../lib/apiClient', () => ({
  ApiError: class ApiError extends Error {},
  api: { del: vi.fn(), get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));
vi.mock('../../lib/permissions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/permissions')>();
  return {
    ...actual,
    usePermissions: () => ({
      matrix: actual.DEFAULT_PERMISSIONS,
      can: () => true,
      toggle: vi.fn(),
      saveError: null,
      clearSaveError: vi.fn(),
    }),
  };
});
vi.mock('../../lib/useServerPage', () => ({
  invalidateServerPageCache: vi.fn(),
  useServerPage: () => ({
    items: USERS,
    page: 1,
    setPage: vi.fn(),
    totalPages: 1,
    total: USERS.length,
    pageSize: 9,
    loading: false,
    error: null,
    reload: vi.fn(),
  }),
}));

import UsersRolesPage from './UsersRolesPage';

function renderPage(search = '') {
  return render(
    <MemoryRouter initialEntries={[`/sozlamalar/foydalanuvchilar${search}`]}>
      <UsersRolesPage />
    </MemoryRouter>,
  );
}

describe('UsersRolesPage — o’chirish tugmalari', () => {
  it("o'zini o'chirish tugmasi sababi bilan o'chirilgan", () => {
    renderPage();
    const button = screen.getAllByLabelText(/Men O‘zim — o'chirib bo'lmaydi/)[0] as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-label')).toContain("O'zingizni o'chira olmaysiz");
  });

  it('oddiy admin Super Admin hisobini o’chira olmaydi', () => {
    renderPage();
    const button = screen.getAllByLabelText(/Bosh Admin — o'chirib bo'lmaydi/)[0] as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-label')).toContain('Faqat Super Admin');
  });

  it("ruxsat etilgan o'chirish tugmasi ishlaydi", () => {
    renderPage();
    const button = screen.getAllByLabelText("Oddiy Xodim — o'chirish")[0] as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
});

describe('UsersRolesPage — huquqlar matritsasi', () => {
  it('Super Admin ustuni qulfi sababini aytadi', () => {
    renderPage('?tab=huquqlar');
    const marks = screen.getAllByLabelText(/— Super Admin: ruxsat/);
    expect(marks.length).toBeGreaterThan(0);
    // Qulf sababi qisqardi, lekin hamon ko'rinadigan va e'lon qilinadigan matn.
    expect(marks[0].getAttribute('aria-label')).toContain("Super Admin huquqlari o'zgarmaydi");
    expect(marks[0].getAttribute('title')).toContain("Super Admin huquqlari o'zgarmaydi");
  });
});

describe('UsersRolesPage — kirish himoyasi', () => {
  it('2FA holati va bino doirasi ko‘rinadi, bekor qilish faqat 2FA yoqilganda', () => {
    renderPage();
    expect(screen.getAllByText('2FA').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2 ta bino').length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText('Men O‘zim — ikki bosqichli kirishni bekor qilish').length).toBeGreaterThan(0);
    expect(screen.queryAllByLabelText('Oddiy Xodim — ikki bosqichli kirishni bekor qilish')).toHaveLength(0);
  });

  it('Super Admin uchun bino doirasi tugmasi yo‘q', () => {
    renderPage();
    expect(screen.queryAllByLabelText('Bosh Admin — bino doirasi')).toHaveLength(0);
    expect(screen.getAllByLabelText('Oddiy Xodim — bino doirasi').length).toBeGreaterThan(0);
  });
});
