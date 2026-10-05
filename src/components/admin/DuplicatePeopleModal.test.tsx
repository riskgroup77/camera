import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const { groups } = vi.hoisted(() => {
  const person = (id: string, fullName: string) => ({
    id, fullName, type: 'xodim', groupOrPosition: 'Kafedra', hasPinfl: false, biometricsStatus: 'tasdiqlangan',
    selfRegistered: false, attendance: 0, createdAt: null,
  });
  return {
    groups: [
      { keeper: person('a', 'Karimov Anvar'), duplicates: [person('b', 'ANVAR KARIMOV')], reason: 'ism_yuz', faceSimilarity: 0.81, mergeable: true },
      { keeper: person('c', 'Olimova Nigora'), duplicates: [person('d', 'Saidova Lola')], reason: 'yuz', faceSimilarity: 0.86, mergeable: false },
    ],
  };
});

vi.mock('../../lib/duplicatesApi', () => ({ getDuplicates: vi.fn().mockResolvedValue(groups), mergeDuplicates: vi.fn() }));

import { ToastProvider } from '../../ui';
import DuplicatePeopleModal from './DuplicatePeopleModal';

describe('DuplicatePeopleModal', () => {
  it("yuz bo'yicha guruhni ko'rsatadi, faqat-yuz juftligini birlashtirishga qo'ymaydi", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <DuplicatePeopleModal open onClose={() => {}} onMerged={() => {}} />
        </ToastProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Yuzi ham mos 81%/)).toBeInTheDocument();
    expect(screen.getByText(/ismi boshqa — birlashtirilmaydi/)).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /birlashtirish \(1\)/ })).toBeEnabled();
  });
});
