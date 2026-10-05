// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { PrivacyPerson } from '../../lib/privacyApi';

const erase = vi.fn();

vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ token: 't', role: 'super-admin', userName: 'Admin' }),
}));

const PERSON: PrivacyPerson = {
  id: 'p1',
  fullName: 'Karimov Aziz',
  type: 'talaba',
  groupOrPosition: 'DI-101',
  facultyName: null,
  active: true,
  deactivatedAt: null,
  hasBiometrics: true,
  biometricsStatus: 'tasdiqlangan',
  consentGivenAt: '2026-09-01T00:00:00Z',
  consentVersion: 'v1',
  consentSource: 'qogoz',
  consentCurrent: true,
  biometricPurgeAt: null,
};

vi.mock('../../lib/privacyApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/privacyApi')>();
  return {
    ...original,
    fetchPrivacyOverview: () =>
      Promise.resolve({
        withBiometrics: 10,
        biometricsWithoutConsent: 2,
        retention: {
          eventRetentionDays: 180,
          snapshotRetentionDays: 90,
          auditLogRetentionDays: 90,
          biometricRetentionDaysAfterInactive: 30,
          accessEventRetentionDays: 365,
          notificationLogRetentionDays: 90,
          recordingRetentionHours: 4,
          eventClipRetentionDays: 30,
        },
      }),
    searchPrivacyPeople: () => Promise.resolve({ items: [PERSON], total: 1, page: 1, pageSize: 20, totalPages: 1 }),
    fetchPersonBiometrics: () =>
      Promise.resolve({
        person: PERSON,
        photoUrl: null,
        faceTemplateStored: true,
        biometricsConfirmedAt: null,
        gallerySamples: 3,
        linkedSightings: 1,
        recentDays: 30,
        recentVisits: 2,
        recentSightings: 7,
        lastSeenAt: null,
      }),
    eraseBiometrics: (...args: unknown[]) => erase(...args),
  };
});

import PrivacyPage from './PrivacyPage';

beforeEach(() => {
  erase.mockReset();
  erase.mockResolvedValue({ person: { ...PERSON, hasBiometrics: false }, photoDeleted: true });
});

async function openPerson() {
  render(
    <MemoryRouter>
      <PrivacyPage />
    </MemoryRouter>,
  );
  fireEvent.change(screen.getByLabelText('Shaxsni qidirish'), { target: { value: 'Karimov' } });
  fireEvent.click(await screen.findByRole('button', { name: /Karimov Aziz/ }));
  await screen.findByText('Kamera namunalari');
}

describe('PrivacyPage', () => {
  it('saqlash muddatlarini ko‘rsatadi', async () => {
    render(
      <MemoryRouter>
        <PrivacyPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText('1 yil')).toBeTruthy();
    expect(screen.getByText('Turniket qaydlari')).toBeTruthy();
    // Video yozuv o'chirilgan (NVR saqlaydi) — arxiv muddati ko'rsatilmaydi.
    expect(screen.queryByText('Video arxiv')).toBeNull();
  });

  it('odam tanlanganda saqlanayotgan biometrika ko‘rinadi', async () => {
    await openPerson();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('7')).toBeTruthy();
  });

  it('o‘chirish familiya yozilmaguncha bajarilmaydi', async () => {
    await openPerson();
    fireEvent.click(screen.getByRole('button', { name: /Biometrikani o‘chirish/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'O‘chirish' }));
    await screen.findByText(/«Karimov» deb yozing/);
    expect(erase).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Tasdiqlash so‘zi'), { target: { value: 'karimov' } });
    fireEvent.click(screen.getByRole('button', { name: 'O‘chirish' }));
    await waitFor(() => expect(erase).toHaveBeenCalledWith('t', 'p1'));
  });
});
