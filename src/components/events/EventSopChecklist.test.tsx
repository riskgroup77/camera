// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EventSopChecklist from './EventSopChecklist';

describe('EventSopChecklist', () => {
  it('har qadam uchun belgi va hisoblagich', () => {
    render(<EventSopChecklist steps={['Kadrni ko‘ring', 'Qo‘riqchini yuboring', 'Izoh yozing']} />);
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(3);
    expect(screen.getByText('0/3')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Qo‘riqchini yuboring'));
    expect((boxes[1] as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('1/3')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Qo‘riqchini yuboring'));
    expect(screen.getByText('0/3')).toBeTruthy();
  });

  it('qadam bo‘lmasa hech narsa chizilmaydi', () => {
    const { container } = render(<EventSopChecklist steps={[]} />);
    expect(container.innerHTML).toBe('');
  });
});
