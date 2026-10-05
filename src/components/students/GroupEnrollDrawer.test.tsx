import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { EnrollMissing } from '../../lib/situationApi';

const missing: EnrollMissing = {
  group: 'DI-2301',
  total: 3,
  missing: [{ id: 'a', fullName: 'Aliyev Anvar', initials: 'AA', biometricsStatus: 'yoq' }],
  enrollUrl: 'https://cam.example/royxatdan-otish?guruh=DI-2301',
  enrollCode: '',
};

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return {
    ...original,
    getEnrollmentMissing: vi.fn(async () => missing),
  };
});
vi.mock('./EnrollQrCard', () => ({ EnrollQrCard: () => null, EnrollPrintPortal: () => null }));

import { GroupEnrollDrawer } from './GroupEnrollDrawer';

function renderDrawer() {
  return render(
    <MemoryRouter>
      <GroupEnrollDrawer target={{ name: 'DI-2301', faculty: 'Davolash ishi' }} onClose={() => {}} withDate={(p) => p} />
    </MemoryRouter>,
  );
}

describe('GroupEnrollDrawer — guruh havolasi', () => {
  it('kod emas, soddalashtirilgan guruh havolasini ko‘rsatadi', async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByText('Topshirmaganlar')).toBeInTheDocument());
    expect(screen.queryByText('Guruh kodi')).toBeNull();
    expect(screen.getByRole('button', { name: 'Havolani nusxalash' })).toBeInTheDocument();
  });
});
