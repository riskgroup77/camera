// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

/**
 * QA: "Tizim → Holat" kartalari.
 *
 * Ilgari: "Ogohlantirish (24 s)" (aslida 24 SOAT), fon yangilanishi xato
 * bersa eski raqamlar jimgina jonli holat kabi turardi, MediaMTX tugunlari
 * topilmasa bo'sh ramka qolib plitka yashil ko'rinardi, GPU rozeti yashil
 * bo'lib yozuvda "CPU ishlatilmoqda" turardi.
 */

vi.mock('../../lib/apiClient', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  buildQuery: () => '',
  isAbortError: () => false,
  ApiError: class extends Error {},
}));

import { CameraNetworkCard } from './CameraNetworkCard';
import { StreamsCard } from './StreamsCard';
import { AiRuntimeCard } from './AiRuntimeCard';
import { ResourceBody, formatServerTime, clockTime } from './parts';
import { RESOURCE_DANGER_AT, RESOURCE_RAG, RESOURCE_WARN_AT, resourceTone } from './systemTypes';
import { rag } from '../../ui/rag';
import type { LiveResource } from '../situation/useLiveResource';
import type { SystemAiStatus, SystemCameraNetwork, SystemStreamStatus } from './systemTypes';

function live<T>(data: T | null, error: string | null = null): LiveResource<T> {
  return { data, error, loading: false, fetching: false, updatedAt: data ? Date.parse('2026-09-20T14:03:00') : null, reload: () => {} };
}

const NET: SystemCameraNetwork = {
  faolCameras: 10,
  reachableCameras: 8,
  offlineCameras: 2,
  linkLocalIpCount: 0,
  chronicOfflineCount: 1,
  offlineAlertMinutes: 5,
  healthIntervalSeconds: 30,
  recentOfflineAlerts24h: 3,
  lastSweep: { finishedAt: '2026-09-20 14:02:10', durationSeconds: 1.25, reachable: 8, faolChecked: 10, skippedOverlap: false },
  recommendation: '',
};

const STREAMS: SystemStreamStatus = {
  shardingEnabled: false,
  shardCount: 0,
  faolCameras: 4,
  registeredStreams: 4,
  shards: [],
  recommendation: '',
};

function aiStatus(gpu: Partial<SystemAiStatus['gpu']>): SystemAiStatus {
  return {
    schedulerEnabled: true,
    schedulerPollSeconds: 120,
    globalSweepConcurrency: 2,
    gpu: { cudaAvailable: true, faceGpuActive: false, objectGpuActive: false, recommendation: '', ...gpu },
    lastTick: { finishedAt: '2026-09-20 14:00:00', durationSeconds: 2, modulesRan: 3, criticalRan: 1, standardRan: 2, skippedOverlap: false },
    sweeps: [],
    sweepSlots: { max: 0, inUse: 0 },
    faceInferenceGate: { max: 2, inUse: 0, waiting: 0 },
  };
}

describe('parts yordamchilari', () => {
  it('server vaqtini o’zbekcha ko’rinishga o’giradi', () => {
    expect(formatServerTime('2026-09-20 14:02:10')).toBe('20.09.2026 14:02');
    expect(formatServerTime('2026-09-20T14:02:10+05:00', true)).toBe('20.09.2026 14:02:10');
    expect(formatServerTime(null)).toBeNull();
  });

  it('clockTime noto’g’ri qiymatda null qaytaradi', () => {
    expect(clockTime(null)).toBeNull();
    expect(clockTime(Number.NaN)).toBeNull();
  });

  it('resurs chegaralari izoh bilan bir xil', () => {
    expect(resourceTone(RESOURCE_WARN_AT)).toBe('success');
    expect(resourceTone(RESOURCE_WARN_AT + 1)).toBe('warning');
    expect(resourceTone(RESOURCE_DANGER_AT + 1)).toBe('danger');
  });

  it('svetofor hukmi resourceTone bilan bir xil chegarada ishlaydi', () => {
    expect(rag(RESOURCE_WARN_AT, RESOURCE_RAG)).toBe('yashil');
    expect(rag(RESOURCE_WARN_AT + 1, RESOURCE_RAG)).toBe('sariq');
    expect(rag(RESOURCE_DANGER_AT + 1, RESOURCE_RAG)).toBe('qizil');
    // O'lchanmagan qiymat hukmsiz qoladi — nol deb ko'rsatilmaydi.
    expect(rag(null, RESOURCE_RAG)).toBe('yoq');
  });
});

describe('ResourceBody', () => {
  it('eski ma’lumot ustida yangilanmagani haqida ogohlantiradi', () => {
    render(
      <ResourceBody resource={live({ x: 1 }, 'Tarmoq xatosi')}>{() => <p>12 ta</p>}</ResourceBody>,
    );
    expect(screen.getByText(/Yangilanmadi/)).toHaveTextContent('Tarmoq xatosi');
    expect(screen.getByText('12 ta')).toBeTruthy();
  });

  it('xato yo’q bo’lsa ogohlantirish chiqmaydi', () => {
    render(<ResourceBody resource={live({ x: 1 })}>{() => <p>12 ta</p>}</ResourceBody>);
    expect(screen.queryByText(/Yangilanmadi/)).toBeNull();
  });
});

describe('CameraNetworkCard', () => {
  it('24 soatlik ogohlantirishlarni soniya emas, soat deb ataydi', () => {
    render(<CameraNetworkCard resource={live(NET)} />);
    expect(screen.getByText('Ogohlantirish (24 soat)')).toBeTruthy();
    expect(screen.queryByText('Ogohlantirish (24 s)')).toBeNull();
  });

  it('"uzoq vaqt offline" chegarasini izohlaydi va tekshiruv vaqtini ko’rsatadi', () => {
    render(<CameraNetworkCard resource={live(NET)} />);
    expect(screen.getByText('5 daqiqadan ortiq')).toBeTruthy();
    expect(screen.getByText(/20\.09\.2026 14:02/)).toBeTruthy();
  });
});

describe('StreamsCard', () => {
  it('tugun topilmasa bo’sh ramka emas, sabab ko’rsatiladi', () => {
    render(<StreamsCard resource={live(STREAMS)} canResync={false} />);
    expect(screen.getByText(/MediaMTX tugunlari topilmadi/)).toBeTruthy();
  });

  it('tugun xatosi ko’rinadigan matn bo’lib chiqadi', () => {
    const withShard: SystemStreamStatus = {
      ...STREAMS,
      shardCount: 1,
      shards: [{ index: 0, reachable: false, pathCount: 0, assignedCameras: 4, error: 'connection refused' }],
    };
    render(<StreamsCard resource={live(withShard)} canResync={false} />);
    expect(screen.getByText('connection refused')).toBeTruthy();
  });
});

describe('AiRuntimeCard', () => {
  it('obyekt GPU faol bo’lsa yozuv "CPU" demaydi', () => {
    render(<AiRuntimeCard resource={live(aiStatus({ objectGpuActive: true }))} />);
    expect(screen.getByText(/CUDA faol \(obyekt\)/)).toBeTruthy();
  });

  it('GPU umuman ishlatilmasa shuni aytadi', () => {
    render(<AiRuntimeCard resource={live(aiStatus({}))} />);
    expect(screen.getByText(/mavjud, CPU ishlatilmoqda/)).toBeTruthy();
  });

  it('sikl davrini "daqiqa" deb emas, haqiqiy davr bilan yozadi', () => {
    render(<AiRuntimeCard resource={live(aiStatus({}))} />);
    expect(screen.getByText('Oxirgi siklda (har 2 daq)')).toBeTruthy();
  });

  it('bo’sh slot (max=0) sariq ko’rinmaydi', () => {
    render(<AiRuntimeCard resource={live(aiStatus({}))} />);
    const value = screen.getByText('0 / 0');
    expect(value.className).not.toContain('warning');
  });
});
