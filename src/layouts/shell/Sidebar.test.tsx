// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { NAV_SECTIONS, visibleSections } from './navConfig';

/**
 * QA: yon panelda faqat o'qiladigan nomlar qoladi; faol band rangsiz ham
 * `aria-current="page"` orqali bilinadi.
 */

function renderSidebar(pathname: string, collapsed = false) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Sidebar
        sections={visibleSections(() => true, 'super-admin')}
        collapsed={collapsed}
        mobileOpen={false}
        onCloseMobile={() => {}}
        userName="Test Foydalanuvchi"
        role="super-admin"
        onLogout={() => {}}
        linkSuffix="?sana=2026-09-21"
      />
    </MemoryRouter>,
  );
}

describe('Sidebar', () => {
  it('shows full item labels without internal index codes', () => {
    renderSidebar('/hodisalar');
    for (const item of NAV_SECTIONS.flatMap((section) => section.items)) {
      expect(screen.getByRole('link', { name: item.label })).toBeInTheDocument();
      expect(screen.queryByText(item.code)).not.toBeInTheDocument();
    }
    // 20+ getByRole so'rovi — to'liq to'plam parallel ishlaganda 5 s yetmasdi.
  }, 20_000);

  it('marks the active item for screen readers, not only by colour', () => {
    renderSidebar('/hodisalar');
    const active = screen.getByRole('link', { name: 'Hodisalar' });
    expect(active).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Talabalar' })).not.toHaveAttribute('aria-current');
  });

  it('counts the items in each section header', () => {
    renderSidebar('/');
    const monitoring = screen.getByRole('button', { name: /Monitoring/ });
    expect(within(monitoring).getByLabelText('6 ta band')).toHaveTextContent('06');
  });

  it('keeps the selected date on attendance links only', () => {
    renderSidebar('/');
    expect(screen.getByRole('link', { name: 'Talabalar' })).toHaveAttribute('href', '/talabalar?sana=2026-09-21');
    expect(screen.getByRole('link', { name: 'Hodisalar' })).toHaveAttribute('href', '/hodisalar');
  });

  it('keeps every page reachable when collapsed', () => {
    renderSidebar('/', true);
    expect(screen.getByRole('link', { name: 'Hodisalar' })).toBeInTheDocument();
    expect(screen.queryByText('HOD')).not.toBeInTheDocument();
  });
});
