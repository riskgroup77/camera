import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ArrivalsChart from './ArrivalsChart';
import type { HourBucket } from '../../lib/arrivals';

const buckets: HourBucket[] = [
  { hour: 7, students: 12, staff: 4, studentsLate: 0, staffLate: 0 },
  { hour: 8, students: 64, staff: 3, studentsLate: 49, staffLate: 1 },
  { hour: 9, students: 58, staff: 0, studentsLate: 58, staffLate: 0 },
  { hour: 10, students: 0, staff: 0, studentsLate: 0, staffLate: 0 },
];

describe('ArrivalsChart', () => {
  it('draws one bar per hour with the late split and the threshold from settings', () => {
    render(<ArrivalsChart buckets={buckets} who="talaba" lateAfter="08:10" isToday={false} onPick={() => {}} />);
    expect(screen.getByRole('button', { name: '08:00–08:59 · 64 kishi keldi, shundan 49 tasi kech' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '07:00–07:59 · 12 kishi keldi, hammasi o‘z vaqtida' })).toBeInTheDocument();
    expect(screen.getByText('08:10 kechikish')).toBeInTheDocument();
    // Rang izohi sarlavhada; pastdagi izoh qatori yo'q.
    expect(screen.getByText('o‘z vaqtida')).toBeInTheDocument();
    expect(screen.queryByText(/dan keyin\)/)).toBeNull();
    expect(screen.queryByText('Ustunni bosing — o‘sha soatda kelganlar')).toBeNull();
    // O'tgan kun: butun ish kuni chiziladi (bo'sh soat tugma emas), "hozir" yo'q.
    expect(screen.getByText('17')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^10:00/ })).toBeNull();
    expect(screen.queryByText(/^hozir/)).toBeNull();
  });

  it('opens the hour on click and with the keyboard', () => {
    const onPick = vi.fn();
    render(<ArrivalsChart buckets={buckets} who="talaba" lateAfter="08:10" isToday={false} onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: /^09:00–09:59/ }));
    fireEvent.keyDown(screen.getByRole('button', { name: /^07:00–07:59/ }), { key: 'Enter' });
    expect(onPick.mock.calls).toEqual([[9], [7]]);
  });

  it('shows staff numbers for the staff view', () => {
    render(<ArrivalsChart buckets={buckets} who="xodim" lateAfter="08:30" isToday={false} />);
    expect(screen.getByRole('group', { name: 'Soatlar bo‘yicha kelganlar: jami 7, shundan 1 tasi kech' })).toBeInTheDocument();
    expect(screen.getByText('08:30 kechikish')).toBeInTheDocument();
    // onPick berilmagan — ustunlar tugma emas.
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('counts arrivals without a time (HEMIS) apart from the hourly bars', () => {
    render(<ArrivalsChart buckets={buckets} who="talaba" lateAfter="08:10" isToday={false} untimed={4802} />);
    // Ustunlar — 134 (vaqti bor), jami — 4 936.
    expect(screen.getByText(/jami 4\s936 · 4\s802 kishining kelish vaqti noma’lum/)).toBeInTheDocument();
    expect(screen.getByRole('group', { name: /yana 4802 kishining kelish vaqti noma’lum/ })).toBeInTheDocument();
  });

  it('explains a day where only untimed arrivals exist', () => {
    const empty = buckets.map((b) => ({ ...b, students: 0, studentsLate: 0 }));
    render(<ArrivalsChart buckets={empty} who="talaba" lateAfter="08:10" isToday={false} untimed={50} />);
    expect(screen.getByText(/Kelish vaqtlari yozilmagan — 50 kishining kelish vaqti noma’lum/)).toBeInTheDocument();
  });

  it('says so plainly when nobody has arrived', () => {
    const empty = buckets.map((b) => ({ ...b, students: 0, studentsLate: 0 }));
    render(<ArrivalsChart buckets={empty} who="talaba" lateAfter="08:10" isToday />);
    expect(screen.getByText('Bugun hali birorta talaba kamerada tanilmagan')).toBeInTheDocument();
  });
});
