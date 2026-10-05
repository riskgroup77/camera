// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../ui';

const RUN = {
  id: 'r1', day: '2026-10-05', status: 'tugadi', windowStart: '2026-10-05T07:00:00+05:00',
  windowEnd: '2026-10-05T20:00:00+05:00', createdAt: null, startedAt: '2026-10-05T20:00:00+05:00',
  finishedAt: '2026-10-05T23:10:00+05:00', jobsTotal: 10, jobsDone: 10, jobsFailed: 0, jobsNoVideo: 1,
  framesPlanned: 1000, framesAnalyzed: 1000, facesDetected: 400, observations: 300, progress: 1, stats: {},
  error: null, triggeredBy: 'tizim',
};
const STATUS = {
  mode: 'kunlik', startTime: '20:00', dayStart: '07:00', nextRunAt: '2026-10-06T20:00:00+05:00', nvrCount: 1,
  mappedCameras: 0, activeCameras: 107, current: null, last: RUN,
};
const SUMMARY = {
  day: '2026-10-05', people: 3, present: 2, late: 1, absent: 1, earlyLeave: 0, lessonsLate: 2, lessonsLeftEarly: 1,
  attentionAvg: 72, coatYes: 1, coatNo: 1, coatUnknown: 1, smoking: 1, teacherOnTime: 1, teacherLate: 1,
  teacherAbsent: 0, teacherActivityAvg: 65, run: RUN,
};
const ROWS = [
  {
    personId: 'p1', fullName: 'Aliyev Vali', type: 'talaba', groupOrPosition: 'DI-101', day: '2026-10-05',
    attendanceStatus: 'kech_keldi', arrivedAt: '2026-10-05T08:22:10+05:00', leftAt: '2026-10-05T16:40:00+05:00',
    lateMinutes: 22, earlyLeave: 'vaqtida', sightings: 8, camerasSeen: 3, lessonsTotal: 3, lessonsAttended: 3,
    lessonsLate: 1, lessonsLeftEarly: 0, lessonsUnmeasured: 0, attentionScore: 55, coatStatus: 'kiymagan',
    coatSamples: 4, coatWhiteSamples: 0, smokingEvents: 1, teacherLessons: null, teacherOnTime: null,
    teacherLate: null, teacherAbsent: null, teacherActivity: null,
  },
];

const getMock = vi.fn(async (path: string) => {
  if (path.startsWith('/api/video-tahlil/holat')) return STATUS;
  if (path.startsWith('/api/video-tahlil/natijalar/xulosa')) return SUMMARY;
  if (path.startsWith('/api/video-tahlil/ishlar')) return [RUN];
  if (path.startsWith('/api/video-tahlil/nvr')) return [];
  throw new Error(`kutilmagan so'rov: ${path}`);
});
const postMock = vi.fn(async (_path: string, _body: unknown) => ({ ...RUN, status: 'navbatda' }));
const serverPageParams = vi.fn();

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ token: 't', role: 'super-admin', userName: 'Admin' }) }));
vi.mock('../../lib/permissions', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/permissions')>();
  return { ...original, usePermissions: () => ({ can: () => true, matrix: {}, toggle: () => {}, saveError: null, clearSaveError: () => {} }) };
});
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return {
    ...original,
    api: { ...original.api, get: (path: string) => getMock(path), post: (path: string, body: unknown) => postMock(path, body) },
  };
});
vi.mock('../../lib/useServerPage', () => ({
  invalidateServerPageCache: vi.fn(),
  useServerPage: (_path: string, params: Record<string, string | undefined>) => {
    serverPageParams(params);
    return { items: ROWS, page: 1, setPage: vi.fn(), totalPages: 1, total: 1, pageSize: 25, loading: false, error: null, reload: vi.fn() };
  },
}));

import VideoAnalysisPage from './VideoAnalysisPage';

function renderAt(url: string) {
  render(
    <ToastProvider>
      <MemoryRouter initialEntries={[url]}>
        <VideoAnalysisPage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  getMock.mockClear();
  postMock.mockClear();
  serverPageParams.mockClear();
});

describe('VideoAnalysisPage', () => {
  it("natijalar: xulosa plitkalari va har odam bo'yicha kriteriyalar", async () => {
    renderAt('/kunlik-tahlil');
    await waitFor(() => expect(screen.getAllByText('Aliyev Vali').length).toBeGreaterThan(0));
    expect(screen.getAllByText('22 daq kech').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Kiymagan').length).toBeGreaterThan(0);
    expect(screen.getAllByText('3/3 · 1 kech').length).toBeGreaterThan(0);
    expect(screen.getAllByText('08:22 – 16:40').length).toBeGreaterThan(0);
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(expect.stringContaining('/api/video-tahlil/natijalar/xulosa?day=2026-10-05')));
    // Plitka bosilsa — o'sha kriteriya bo'yicha filtr.
    fireEvent.click(screen.getAllByText('Oq xalatsiz')[0]);
    await waitFor(() => expect(serverPageParams).toHaveBeenLastCalledWith(expect.objectContaining({ filter: 'xalatsiz' })));
    fireEvent.click(screen.getAllByText('Oq xalatsiz')[0]);
    await waitFor(() => expect(serverPageParams).toHaveBeenLastCalledWith(expect.objectContaining({ filter: undefined })));
  });

  it("tahlil jarayoni: kunni qo'lda ishga tushirish", async () => {
    renderAt('/kunlik-tahlil?tab=tahlil');
    await screen.findByText(/Hozir tahlil ketmayapti/);
    fireEvent.click(screen.getByRole('button', { name: /Shu kunni tahlil qilish/ }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/video-tahlil/ishlar', expect.objectContaining({ day: expect.any(String) })));
  });

  it("NVR: kamera bog'lanmagan bo'lsa ogohlantiradi", async () => {
    renderAt('/kunlik-tahlil?tab=nvr');
    await screen.findByText(/birorta kamera NVR kanaliga bog'lanmagan/);
    expect(screen.getByText("NVR qo'shilmagan")).toBeInTheDocument();
  });
});
