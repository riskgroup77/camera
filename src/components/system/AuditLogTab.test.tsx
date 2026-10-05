// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

/**
 * QA: "Tizim → Jurnal" tabi.
 *
 * Ilgari: hisoblagichlar so'rovi xato bersa uchala plitka cheksiz
 * "yuklanmoqda" skeletonida qolardi; vaqt ustuni "2026-09-20 14:03:22"
 * ko'rinishida edi (ilovaning qolgan qismida 20.09.2026); tanlangan filtr
 * faqat ramka rangi bilan bildirilardi.
 */

const EMPTY_PAGE = { items: [], total: 0, page: 1, pageSize: 1, totalPages: 0 };

// Spy'ning standart implementatsiyasi async bo'lishi shart — aks holda
// mockReset'dan keyin u promise emas, undefined qaytaradi va vitest rad
// javoblarini "unhandled" deb belgilaydi.
const apiGet = vi.fn(async () => EMPTY_PAGE as unknown);

vi.mock('../../lib/apiClient', () => ({
  api: { get: (...args: unknown[]) => apiGet(...(args as [])), post: vi.fn() },
  buildQuery: () => '',
  isAbortError: () => false,
  ApiError: class extends Error {},
}));

vi.mock('../../lib/useServerPage', () => ({
  useServerPage: () => ({
    items: [{ id: '1', timestamp: '2026-09-20 14:03:22', user: 'Admin', action: 'Kirish', module: 'Tizim', status: 'muvaffaqiyatli', ip: '10.0.0.1' }],
    page: 1,
    setPage: () => {},
    totalPages: 1,
    total: 1,
    pageSize: 20,
    loading: false,
    refreshing: false,
    error: null,
    reload: () => {},
  }),
}));

import { AuditLogTab } from './AuditLogTab';

beforeEach(() => {
  apiGet.mockReset();
  apiGet.mockImplementation(async () => EMPTY_PAGE as unknown);
});

describe('AuditLogTab', () => {
  it('hisoblagichlar so’rovi xato bersa plitkalar skeletonda qolmaydi', async () => {
    apiGet.mockImplementation(async () => {
      throw new Error('500');
    });
    render(<AuditLogTab canExport={false} />);
    // Qiymat noma'lum — "—" bilan, lekin plitka skeletondan chiqadi.
    await waitFor(() => expect(screen.getAllByText('—').length).toBe(3));
  });

  it('vaqtni o’zbekcha formatda ko’rsatadi', async () => {
    render(<AuditLogTab canExport={false} />);
    expect((await screen.findAllByText('20.09.2026 14:03:22')).length).toBeGreaterThan(0);
  });

  // Tushuntirish matni olib tashlandi; bosiladigan ekani endi `aria-pressed`
  // orqali e'lon qilinadi — filtr holati hamon ekran o'quvchiga yetadi.
  it('plitkalar bosiladigan filtr sifatida e’lon qilinadi', async () => {
    const { container } = render(<AuditLogTab canExport={false} />);
    await screen.findAllByRole('button');
    expect(container.querySelectorAll('button[aria-pressed]').length).toBe(3);
  });
});
