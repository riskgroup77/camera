import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { WallUnit } from '../../lib/wallApi';
import { RankingPanel } from './RankingPanel';

const unit = (id: string, rate: number): WallUnit => ({
  id,
  name: `Bo'linma ${id}`,
  kind: 'kafedra',
  total: 10,
  present: Math.round(rate / 10),
  rate,
});

describe('RankingPanel', () => {
  it("sarlavhadagi son haqiqiy qatorlar soniga teng (qattiq '5' emas)", () => {
    render(<RankingPanel top={[unit('a', 90), unit('b', 80)]} bottom={[]} chronic={4} />);
    expect(screen.getByText('Eng yaxshi 2')).toBeInTheDocument();
    expect(screen.queryByText('Eng yaxshi 5')).toBeNull();
  });

  it("surunkali hisob kelmaganda '—' ning sababi yoziladi", () => {
    const { rerender } = render(<RankingPanel top={[unit('a', 90)]} bottom={[]} chronic={null} />);
    expect(screen.getByText(/yuklanmoqda/)).toBeInTheDocument();

    rerender(<RankingPanel top={[unit('a', 90)]} bottom={[]} chronic={null} chronicError />);
    expect(screen.getByText('olinmadi')).toBeInTheDocument();
  });

  it('hisob kelganda raqam yolg\'iz turadi — tushuntirish yo\'q', () => {
    render(<RankingPanel top={[unit('a', 90)]} bottom={[]} chronic={7} />);
    expect(screen.getByText('7')).toBeInTheDocument();
    // Yorliq qoladi, izoh esa sichqoncha ostiga (title) ko'chdi.
    expect(screen.getByText('Takror kechikkan')).toBeInTheDocument();
    expect(screen.queryByText(/yuklanmoqda|olinmadi/)).toBeNull();
  });
});
