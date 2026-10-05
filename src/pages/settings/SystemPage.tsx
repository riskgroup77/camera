import { Activity, Cctv, RefreshCw, ScrollText } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { IconButton, Page, useUrlTab, type TabItem } from '../../ui';
import { useRefreshTicker } from '../../components/situation/useLiveResource';
import { AuditLogTab } from '../../components/system/AuditLogTab';
import { CameraHealthTab } from '../../components/system/CameraHealthTab';
import { SystemHealthTab } from '../../components/system/SystemHealthTab';

type SystemTab = 'holat' | 'kameralar' | 'jurnal';

const TABS: readonly TabItem<SystemTab>[] = [
  { id: 'holat', label: 'Holat', icon: Activity },
  { id: 'kameralar', label: 'Kameralar', icon: Cctv },
  { id: 'jurnal', label: 'Jurnal', icon: ScrollText },
];

/** Tizim: texnik holat (server, AI, oqimlar, kamera tarmog'i), har bir
 *  kameraning salomatligi va audit jurnali. */
export default function SystemPage() {
  const { role } = useAuth();
  const { can } = usePermissions();
  const [tab] = useUrlTab(TABS);
  // Holat va Kameralar 30 s da bir yangilanadi (faqat shu tab ochiq bo'lsa).
  const live = tab === 'holat' || tab === 'kameralar';
  const { tick, refreshNow } = useRefreshTicker(30_000, live);

  return (
    <Page
      title="Tizim holati"
      breadcrumbs={[{ label: 'Sozlamalar' }, { label: 'Tizim holati' }]}
      tabs={TABS}
      actions={live ? <IconButton icon={RefreshCw} label="Yangilash" variant="secondary" size="sm" onClick={refreshNow} /> : undefined}
    >
      {tab === 'holat' ? (
        <SystemHealthTab tick={tick} canResync={can('systemSettings', role)} canManageHemis={can('manageIntegrations', role)} />
      ) : tab === 'kameralar' ? (
        <CameraHealthTab tick={tick} />
      ) : (
        <AuditLogTab canExport={can('exportData', role)} />
      )}
    </Page>
  );
}
