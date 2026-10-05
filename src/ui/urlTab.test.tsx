import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { Page } from './Page';
import { nextTabParams, resolveTab, useUrlTab, type TabItem } from './urlTab';

type Id = 'umumiy' | 'jurnal' | 'eski';
const TABS: TabItem<Id>[] = [
  { id: 'umumiy', label: 'Umumiy' },
  { id: 'jurnal', label: 'Jurnal' },
  { id: 'eski', label: 'Eski', disabled: true },
];

describe('resolveTab', () => {
  it('uses the URL value only when it is a known, enabled tab', () => {
    expect(resolveTab('jurnal', TABS)).toBe('jurnal');
    expect(resolveTab('eski', TABS)).toBe('umumiy');
    expect(resolveTab('yoq', TABS, 'jurnal')).toBe('jurnal');
    expect(resolveTab(null, TABS)).toBe('umumiy');
  });

  it('drops the param for the default tab and keeps other params', () => {
    const current = new URLSearchParams('sana=2026-09-01&tab=jurnal');
    expect(nextTabParams(current, 'umumiy', 'umumiy').toString()).toBe('sana=2026-09-01');
    expect(nextTabParams(current, 'jurnal', 'umumiy').toString()).toBe('sana=2026-09-01&tab=jurnal');
  });
});

function Probe() {
  const [tab] = useUrlTab(TABS);
  const location = useLocation();
  return (
    <p data-testid="probe">
      {tab}|{location.search}
    </p>
  );
}

describe('Page tabs sync with ?tab=', () => {
  it('reads the initial tab from the URL and writes clicks back', () => {
    render(
      <MemoryRouter initialEntries={['/sozlamalar/tizim?tab=jurnal&sana=2026-09-01']}>
        <Page title="Tizim" tabs={TABS}>
          <Probe />
        </Page>
      </MemoryRouter>,
    );
    expect(screen.getByRole('tab', { name: 'Jurnal' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('probe')).toHaveTextContent('jurnal|?tab=jurnal&sana=2026-09-01');

    act(() => {
      fireEvent.click(screen.getByRole('tab', { name: 'Umumiy' }));
    });
    expect(screen.getByRole('tab', { name: 'Umumiy' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('probe')).toHaveTextContent('umumiy|?sana=2026-09-01');
  });

  it('supports arrow-key navigation and skips disabled tabs', () => {
    render(
      <MemoryRouter initialEntries={['/x']}>
        <Page title="Tizim" tabs={TABS}>
          <Probe />
        </Page>
      </MemoryRouter>,
    );
    act(() => {
      fireEvent.keyDown(screen.getByRole('tab', { name: 'Umumiy' }), { key: 'ArrowRight' });
    });
    expect(screen.getByTestId('probe')).toHaveTextContent('jurnal|?tab=jurnal');
    act(() => {
      fireEvent.keyDown(screen.getByRole('tab', { name: 'Jurnal' }), { key: 'ArrowRight' });
    });
    expect(screen.getByTestId('probe').textContent).toBe('umumiy|');
  });
});
