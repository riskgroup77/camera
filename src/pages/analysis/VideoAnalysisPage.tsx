import { useCallback, useEffect, useMemo, useState } from 'react';
import { HardDrive, ListChecks, PlayCircle, RefreshCw } from 'lucide-react';
import { Badge, IconButton, Page, useUrlTab, type TabItem } from '../../ui';
import { usePageVisible } from '../../components/videowall/usePageVisible';
import NvrTab from '../../components/videoAnalysis/NvrTab';
import ResultsTab from '../../components/videoAnalysis/ResultsTab';
import RunsTab from '../../components/videoAnalysis/RunsTab';
import { useAuth } from '../../lib/auth';
import { usePermissions } from '../../lib/permissions';
import { RUN_STATUS_META, isRunActive, videoAnalysisApi, type AnalysisStatus } from '../../lib/videoAnalysisApi';

type AnalysisTab = 'natijalar' | 'tahlil' | 'nvr';

/** Ishlayotgan tahlil holati shu oraliqda yangilanadi. */
const ACTIVE_REFRESH_MS = 10_000;

/** Kunlik video tahlil: kun oxirida NVR yozuvlaridan hisoblangan
 *  kriteriyalar (davomat, darslar, diqqat, xalat, chekish, o'qituvchi). */
export default function VideoAnalysisPage() {
  const { token, role } = useAuth();
  const { can } = usePermissions();
  const canManage = can('systemSettings', role);
  const tabs = useMemo<readonly TabItem<AnalysisTab>[]>(
    () => [
      { id: 'natijalar', label: 'Natijalar', icon: ListChecks },
      { id: 'tahlil', label: 'Tahlil jarayoni', icon: PlayCircle },
      ...(canManage ? [{ id: 'nvr' as const, label: 'NVR', icon: HardDrive }] : []),
    ],
    [canManage],
  );
  const [tab] = useUrlTab(tabs);
  const visible = usePageVisible();
  const [status, setStatus] = useState<AnalysisStatus | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await videoAnalysisApi.status(token));
    } catch {
      setStatus(null);
    }
  }, [token]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const active = isRunActive(status?.current);
  useEffect(() => {
    if (!active || !visible) return;
    const timer = window.setInterval(() => void loadStatus(), ACTIVE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active, visible, loadStatus]);

  const lastDay = status?.last?.status === 'tugadi' ? status.last.day : null;
  const current = status?.current;

  return (
    <Page
      title="Kunlik tahlil"
      subtitle={
        status
          ? `Har kuni ${status.startTime} da NVR yozuvlari (${status.dayStart}–${status.startTime}) tahlil qilinadi`
          : undefined
      }
      titleAddon={current ? <Badge tone={RUN_STATUS_META[current.status].tone} dot>{RUN_STATUS_META[current.status].label}</Badge> : undefined}
      breadcrumbs={[{ label: 'Tahlil' }, { label: 'Kunlik tahlil' }]}
      tabs={tabs}
      actions={<IconButton icon={RefreshCw} label="Yangilash" variant="secondary" size="sm" onClick={() => void loadStatus()} />}
    >
      {tab === 'natijalar' ? (
        <ResultsTab key={lastDay ?? 'none'} lastDay={lastDay} />
      ) : tab === 'tahlil' ? (
        <RunsTab status={status} canManage={canManage} onChanged={() => void loadStatus()} />
      ) : (
        <NvrTab mappedCameras={status?.mappedCameras ?? 0} activeCameras={status?.activeCameras ?? 0} />
      )}
    </Page>
  );
}
