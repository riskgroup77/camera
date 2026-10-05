// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

/**
 * QA: bildirishnoma qoidasi oynasi.
 *
 * Kanal almashtirilganda yangi kanalga mos kelmaydigan qabul qiluvchilar
 * olib tashlanadi — ilgari bu JIMGINA bo'lardi. SMS ni ko'rib qaytgan odam
 * Telegram chat ID larini yo'qotib, sababini bilmay qolardi.
 */

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin' }) }));
vi.mock('../../lib/useAiModules', () => ({ useAiModules: () => ({ modules: [] }) }));
vi.mock('../../lib/useBuildings', () => ({ useBuildings: () => ({ buildings: [] }) }));

import NotificationRuleModal from './NotificationRuleModal';
import type { NotificationRule } from '../../lib/notificationsApi';

const RULE = {
  id: 'r1',
  name: 'Navbatchilar',
  enabled: true,
  channel: 'telegram',
  recipients: ['-1001234567890', '@navbat'],
  kinds: ['event'],
  moduleCodes: null,
  buildingIds: null,
  minSeverity: null,
} as unknown as NotificationRule;

describe('NotificationRuleModal — kanal almashtirish', () => {
  it("SMS ga o'tganda yo'qotilgan Telegram qabul qiluvchilarini aytadi", () => {
    render(<NotificationRuleModal open rule={RULE} onClose={() => {}} onSaved={() => {}} />);

    expect(screen.getByText('-1001234567890')).toBeTruthy();

    fireEvent.click(screen.getByRole('radio', { name: /SMS/i }));

    const warning = screen.getByText(/olib tashlandi/i);
    expect(warning).toBeTruthy();
    expect(warning.parentElement?.textContent).toContain('-1001234567890');
    expect(warning.parentElement?.textContent).toContain('@navbat');
  });
});

describe('NotificationRuleModal — sozlanmagan kanal', () => {
  const STATUS = {
    telegramConfigured: true,
    telegramBotUsername: 'bot',
    telegramPollingEnabled: true,
    smsProvider: 'eskiz',
    smsConfigured: false,
    smsSender: null,
    parentArrivalEnabled: false,
    parentAbsenceEnabled: false,
    orgName: 'Test',
  };

  it('SMS sozlanmagan bo\'lsa, SMS tanlanganda ogohlantiradi', () => {
    render(<NotificationRuleModal open rule={null} status={STATUS} onClose={() => {}} onSaved={() => {}} />);

    expect(screen.queryByText(/kanali sozlanmagan/i)).toBeNull();

    fireEvent.click(screen.getByRole('radio', { name: /SMS/i }));

    expect(screen.getByText(/kanali sozlanmagan/i)).toBeTruthy();
  });
});
