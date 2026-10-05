// @vitest-environment jsdom
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import RecipientChipsInput from './RecipientChipsInput';
import type { NotificationChannel } from '../../lib/notificationsApi';

/**
 * QA: qabul qiluvchilar maydoni.
 *
 * Ikki jimgina yo'qotish tuzatildi: takroriy qiymat hech nima demasdan
 * yo'qolardi, kanal almashtirilganda esa eski qoralama va uning xatosi
 * ekranda qolib, saqlashni bloklardi.
 */

function Harness({ initial = [], initialChannel = 'telegram' as NotificationChannel }: { initial?: string[]; initialChannel?: NotificationChannel }) {
  const [value, setValue] = useState<string[]>(initial);
  const [channel, setChannel] = useState<NotificationChannel>(initialChannel);
  const [draft, setDraft] = useState('');
  return (
    <>
      <button type="button" onClick={() => setChannel(channel === 'telegram' ? 'sms' : 'telegram')}>
        kanal
      </button>
      <span data-testid="draft">{draft}</span>
      <RecipientChipsInput channel={channel} value={value} onChange={setValue} onDraftChange={setDraft} />
    </>
  );
}

const input = () => screen.getByLabelText(/Qabul qiluvchilar/i) as HTMLInputElement;

function type(text: string) {
  fireEvent.change(input(), { target: { value: text } });
  fireEvent.keyDown(input(), { key: 'Enter' });
}

describe('RecipientChipsInput', () => {
  it("takroriy qabul qiluvchi jimgina yo'qolmaydi — sababi aytiladi", () => {
    render(<Harness initial={['123456789']} />);
    type('123456789');

    expect(screen.getByText(/allaqachon qo'shilgan/i)).toBeTruthy();
    // Chip ikkilanmaydi.
    expect(screen.getAllByText('123456789')).toHaveLength(1);
  });

  it("yangi qiymat qo'shilganda ogohlantirish ketadi", () => {
    render(<Harness initial={['123456789']} />);
    type('123456789');
    expect(screen.queryByText(/allaqachon qo'shilgan/i)).toBeTruthy();

    type('987654321');
    expect(screen.queryByText(/allaqachon qo'shilgan/i)).toBeNull();
  });

  it("kanal almashtirilganda eski qoralama va xato tozalanadi", () => {
    render(<Harness initialChannel="sms" />);

    // SMS uchun yaroqsiz raqam — xato chiqadi, qoralama saqlanib qoladi.
    type('12');
    expect(screen.getByText(/Telefon raqami noto'g'ri/i)).toBeTruthy();
    expect(screen.getByTestId('draft').textContent).toBe('12');

    fireEvent.click(screen.getByRole('button', { name: 'kanal' }));

    expect(screen.queryByText(/Telefon raqami noto'g'ri/i)).toBeNull();
    expect(input().value).toBe('');
    // Forma endi "«12» hali qo'shilmadi" deb saqlashni to'xtatmaydi.
    expect(screen.getByTestId('draft').textContent).toBe('');
  });
});
