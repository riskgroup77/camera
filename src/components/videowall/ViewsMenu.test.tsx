import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { WallView } from '../../lib/videoWall';
import ViewsMenu from './ViewsMenu';

const view = (id: string, name: string): WallView => ({
  id,
  name,
  layout: '2x2',
  tiles: ['cam-1', null, null, null],
  updatedAt: '2026-09-24T10:00:00.000Z',
});

function renderMenu() {
  const noop = vi.fn();
  render(
    <ViewsMenu
      views={[view('a', 'Meniki'), view('b', 'Begona')]}
      meta={{
        a: { mine: true, canEdit: true, shared: true, ownerName: 'Men' },
        b: { mine: false, canEdit: false, shared: true, ownerName: 'Behzod Karimov' },
      }}
      remote
      activeViewId={null}
      dirty={false}
      onApply={noop}
      onSaveNew={noop}
      onUpdate={noop}
      onRename={noop}
      onDelete={noop}
      onExport={noop}
      onImport={noop}
      onOpenWindow={noop}
    />,
  );
  fireEvent.click(screen.getByTitle("Saqlangan ko'rinishlar"));
}

describe('ViewsMenu', () => {
  it("boshqaning ko'rinishida «umumiy» belgisi bor, tahrirlash tugmalari yo'q", () => {
    renderMenu();
    expect(screen.getByText('serverda saqlanadi')).toBeInTheDocument();
    const badges = screen.getAllByText('umumiy');
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveAttribute('title', 'Behzod Karimov ulashgan');
    // Faqat o'z ko'rinishini o'chirish/qayta nomlash mumkin.
    expect(screen.getAllByRole('button', { name: "O'chirish" })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: "Nomini o'zgartirish" })).toHaveLength(1);
  });
});
