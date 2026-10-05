// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Breadcrumbs, ConnectionLamp, LiveClock } from './TopbarWidgets';

/**
 * QA: yuqori paneldagi asboblar.
 *
 * Soat — HAQIQIY Toshkent vaqti, va fonga o'tgan yorliqda taymer
 * umuman ishlamaydi (ochiq turgan devor ekrani bekorga qayta
 * chizilmasin). Ulanish chirog'i esa har doim SO'Z bilan chiqadi —
 * rangni ajratmaydigan operator ham holatni o'qiydi.
 */

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('LiveClock', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // 2026-09-21 07:04:05 UTC → Toshkent (UTC+5) 12:04:05.
    vi.setSystemTime(new Date('2026-09-21T07:04:05Z'));
    setVisibility('visible');
  });
  afterEach(() => {
    setVisibility('visible');
    vi.useRealTimers();
  });

  it('shows Tashkent time with seconds', () => {
    render(<LiveClock seconds />);
    expect(screen.getByText('12:04:05')).toBeInTheDocument();
  });

  it('ticks while visible', () => {
    render(<LiveClock seconds />);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText('12:04:06')).toBeInTheDocument();
  });

  it('stops the timer while the tab is hidden and catches up on return', () => {
    render(<LiveClock seconds />);
    act(() => setVisibility('hidden'));
    expect(vi.getTimerCount()).toBe(0);

    act(() => vi.advanceTimersByTime(300_000));
    expect(screen.getByText('12:04:05')).toBeInTheDocument();

    act(() => setVisibility('visible'));
    expect(screen.getByText('12:09:05')).toBeInTheDocument();
  });
});

describe('ConnectionLamp', () => {
  it('always puts a word next to the colour', () => {
    const { rerender } = render(<ConnectionLamp status="live" />);
    expect(screen.getByText('Jonli')).toBeInTheDocument();
    rerender(<ConnectionLamp status="connecting" />);
    expect(screen.getByRole('status')).toHaveAccessibleName(/qayta ulanmoqda/i);
    rerender(<ConnectionLamp status="paused" />);
    expect(screen.getByText("To'xtadi")).toBeInTheDocument();
  });
});

describe('Breadcrumbs', () => {
  it('links the parent crumb and marks the last one as the current page', () => {
    render(
      <MemoryRouter>
        <Breadcrumbs crumbs={[{ label: 'Davomat', to: '/talabalar' }, { label: 'Talabalar' }]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Davomat' })).toHaveAttribute('href', '/talabalar');
    expect(screen.getByText('Talabalar').closest('[aria-current]')).not.toBeNull();
  });
});
