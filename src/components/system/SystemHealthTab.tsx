import { AlertTriangle, ShieldAlert } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { MicroLabel } from '../../ui';
import { useLiveResource } from '../situation/useLiveResource';
import { AiRuntimeCard } from './AiRuntimeCard';
import { CameraNetworkCard } from './CameraNetworkCard';
import { HemisCard } from './HemisCard';
import { ServerResourcesCard } from './ServerResourcesCard';
import { StreamsCard } from './StreamsCard';
import type {
  SystemAiStatus,
  SystemCameraNetwork,
  SystemResources,
  SystemStreamStatus,
} from './systemTypes';

interface Props {
  tick: number;
  canResync: boolean;
  canManageHemis: boolean;
}

interface ActiveProblem {
  key: string;
  title: string;
  message: string;
}

/** "Holat" tabi — asboblar paneli: server, AI, oqimlar, kamera tarmog'i. */
export function SystemHealthTab({ tick, canResync, canManageHemis }: Props) {
  const problems = useLiveResource('alerts', (signal) => api.get<ActiveProblem[]>('/api/system/alerts', undefined, { signal }), tick);
  const resources = useLiveResource('resources', (signal) => api.get<SystemResources>('/api/system/resources', undefined, { signal }), tick);
  const ai = useLiveResource('ai', (signal) => api.get<SystemAiStatus>('/api/system/ai-status', undefined, { signal }), tick);
  const streams = useLiveResource('streams', (signal) => api.get<SystemStreamStatus>('/api/system/stream-status', undefined, { signal }), tick);
  const network = useLiveResource('network', (signal) => api.get<SystemCameraNetwork>('/api/system/camera-network', undefined, { signal }), tick);
  const r = resources.data;
  const security = r?.alerts.filter((a) => a.metric === 'security') ?? [];

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {security.map((alert) => (
        <div key={alert.message} role="alert" className="flex items-start gap-3 border border-danger/40 bg-danger-soft px-3 py-2">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
          <div className="min-w-0">
            <MicroLabel className="!text-danger">Xavfsizlik</MicroLabel>
            <p className="text-[13px] text-fg">{alert.message}</p>
          </div>
        </div>
      ))}

      {/* Telegramga ketadigan tizim ogohlantirishlari (app/jobs/system_alerts.py) — shu yerda ham. */}
      {(problems.data ?? []).map((problem) => (
        <div key={problem.key} role="alert" className="flex items-start gap-3 border border-warning/50 bg-warning-soft px-3 py-2">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
          <div className="min-w-0">
            <MicroLabel>{problem.title}</MicroLabel>
            <p className="text-[13px] text-fg">{problem.message}</p>
          </div>
        </div>
      ))}

      <div className="grid gap-3 lg:grid-cols-2">
        <ServerResourcesCard resource={resources} />
        <AiRuntimeCard resource={ai} />
        <StreamsCard resource={streams} canResync={canResync} />
        <CameraNetworkCard resource={network} />
        {canManageHemis && <HemisCard tick={tick} />}
      </div>

    </div>
  );
}
