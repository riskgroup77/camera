import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import GroupCriteriaTable, { cellSortValue } from './GroupCriteriaTable';
import type { GroupCriteria } from '../../lib/groupCriteriaApi';

const data: GroupCriteria = {
  group: 'DI-2301',
  period: { from: '2026-10-06', to: '2026-10-06', days: 1 },
  analysed: false,
  criteria: [
    { key: 'davomat', code: 7, label: 'Kelgan-kelmagani', description: 'kun davomida', indicator: '50%', tone: 'danger', unavailable: null, note: null },
    { key: 'forma', code: 10, label: 'Oq xalatsiz yurganlar', description: 'oq xalat', indicator: '—', tone: 'neutral', unavailable: 'Bu kun hali video tahlil qilinmagan', note: null },
  ],
  people: [
    {
      id: 'a',
      full_name: 'Aliyev Anvar',
      initials: 'AA',
      enrolled: true,
      cells: {
        davomat: { value: 'kech', tone: 'warning', title: 'Kech keldi 08:42 da', evidence: 1 },
        forma: { value: '—', tone: 'neutral', title: 'Bu kun hali video tahlil qilinmagan', evidence: null },
      },
    },
    {
      id: 'b',
      full_name: 'Botirova Nigora',
      initials: 'BN',
      enrolled: false,
      cells: {
        davomat: { value: 'kelmadi', tone: 'danger', title: 'Kun davomida kamerada ko‘rinmadi', evidence: null },
        forma: { value: '—', tone: 'neutral', title: '', evidence: null },
      },
    },
  ],
};

describe('GroupCriteriaTable', () => {
  it('shows every student with every criterion, codes and video evidence', () => {
    render(
      <MemoryRouter>
        <GroupCriteriaTable data={data} loading={false} error={null} />
      </MemoryRouter>,
    );
    // Sarlavha: buyurtmachi raqami + qisqa nom, izohda — sabab.
    const table = screen.getByRole('table');
    expect(within(table).getByTitle('7. Kelgan-kelmagani — kun davomida')).toHaveTextContent('7Davomat');
    // Hisoblanmayotgan kriteriya ham ustun bo'lib turadi — izohida sababi.
    expect(within(table).getByTitle('10. Oq xalatsiz yurganlar — Bu kun hali video tahlil qilinmagan')).toHaveTextContent('Oq xalat');
    const anvar = within(table).getByText('Aliyev Anvar').closest('tr')!;
    expect(within(anvar).getByText('kech')).toHaveClass('text-warning');
    expect(within(anvar).getByTitle('1 ta 2 daqiqalik video dalil — talaba sahifasida')).toBeInTheDocument();
    expect(within(anvar).getByRole('link')).toHaveAttribute('href', '/shaxs/a');
    // Yuzi bazada yo'q — kamera taniy olmaydi.
    expect(within(table).getByText('· yuzsiz')).toBeInTheDocument();
  });

  it('sorts problems first and keeps not-measured cells last', () => {
    const danger = cellSortValue({ value: '2', tone: 'danger', title: '', evidence: null });
    const warning = cellSortValue({ value: '+32 daq', tone: 'warning', title: '', evidence: null });
    const fine = cellSortValue({ value: 'keldi', tone: 'success', title: '', evidence: null });
    const none = cellSortValue({ value: '—', tone: 'neutral', title: '', evidence: null });
    expect(danger).toBeGreaterThan(warning);
    expect(warning).toBeGreaterThan(fine);
    expect(fine).toBeGreaterThan(none);
  });
});
