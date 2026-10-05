import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { LastArrival } from '../../lib/situationApi';
import { ArrivalsPanel } from './ArrivalsPanel';

const arrival = (over: Partial<LastArrival> = {}): LastArrival => ({
  id: 'p1',
  fullName: 'Ali Valiyev',
  photoUrl: null,
  initials: 'AV',
  type: 'xodim',
  unit: 'Kafedra',
  time: '08:12',
  faculty: null,
  status: 'keldi',
  ...over,
});

describe('ArrivalsPanel — "jonli" yorlig\'i', () => {
  it('aloqa borida "jonli" deyiladi', () => {
    render(<ArrivalsPanel arrivals={[arrival()]} freshIds={new Set()} live />);
    expect(screen.getByText('jonli')).toBeInTheDocument();
  });

  it("aloqa uzilganda 'jonli' o'rniga ogohlantirish chiqadi", () => {
    render(<ArrivalsPanel arrivals={[arrival()]} freshIds={new Set()} live={false} />);
    expect(screen.queryByText('jonli')).toBeNull();
    expect(screen.getByText("aloqa yo'q")).toBeInTheDocument();
  });
});
