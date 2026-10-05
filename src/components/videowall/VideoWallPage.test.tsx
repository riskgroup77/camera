import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import VideoWallPage from '../../pages/admin/VideoWallPage';
import { WALL_MAX_LIVE } from '../../lib/videoWall';
import type { CameraFeed } from '../../types';
import { DRAG_CAMERA } from './WallTile';

const cameras: CameraFeed[] = Array.from({ length: 30 }, (_, index) => ({
  id: `cam-${index + 1}`,
  name: `Kamera ${index + 1}`,
  building: index < 20 ? '1-Bino' : '2-Bino',
  zone: `${100 + index}-xona`,
  status: index === 1 ? 'offline' : 'live',
  streamUrl: `https://cam.example/s0/cam-${index + 1}/index.m3u8`,
  floor: (index % 3) + 1,
}));

/** Serverdan keladigan ro'yxat — sinov ichida almashtiriladi (kamera
 *  o'chirildi / so'rov xato berdi). */
let feed: () => Promise<CameraFeed[]> = async () => cameras;

vi.mock('../../lib/apiClient', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/apiClient')>();
  return {
    ...original,
    fetchAllPages: vi.fn(() => feed()),
    api: { ...original.api, blob: vi.fn(async () => Promise.reject(new Error('kadr yo‘q'))) },
  };
});
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ role: 'admin' }) }));
vi.mock('../../lib/permissions', () => ({ usePermissions: () => ({ can: () => false }) }));
vi.mock('../LiveVideoPlayer', () => ({
  default: ({ streamUrl }: { streamUrl?: string }) => <div data-testid="player" data-url={streamUrl} />,
}));

/** Boshqa varaqdagi havolani taqlid qiladi: bosilganda manzil o'zgaradi,
 *  sahifa esa qayta yuklanmaydi (aynan shu holat sinovdan o'tadi). */
function LinkLike({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(to)}>
      {label}
    </button>
  );
}

function renderWall(entry = '/videodevor', extra?: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <VideoWallPage />
      {extra}
    </MemoryRouter>,
  );
}

const cells = () => screen.getAllByRole('gridcell');
const players = () => screen.queryAllByTestId('player');

async function loaded() {
  await waitFor(() => expect(screen.getByText(/30 ta ·/)).toBeInTheDocument());
}

/** Yon panel bino daraxtidan ochiladi — tekis ro'yxatga o'tish. */
async function loadedFlat() {
  await loaded();
  fireEvent.click(screen.getByRole('button', { name: /^Barcha kameralar/ }));
}

beforeEach(() => {
  localStorage.clear();
  feed = async () => cameras;
});

afterEach(() => {
  localStorage.clear();
});

describe('Videodevor', () => {
  it("yon paneldan bosilgan kamera birinchi bo'sh katakka tushadi va jonli o'ynaydi", async () => {
    renderWall();
    await loadedFlat();
    expect(cells()).toHaveLength(4);
    expect(players()).toHaveLength(0);

    fireEvent.click(screen.getByTitle(/Kamera 1 —/));
    expect(players()).toHaveLength(1);
    expect(players()[0]).toHaveAttribute('data-url', cameras[0].streamUrl);

    // Oflayn kamera pleyer ochmaydi — joy egallovchi ko'rsatiladi.
    fireEvent.click(screen.getByTitle(/Kamera 2 —/));
    expect(players()).toHaveLength(1);
    expect(screen.getByText('OFLAYN')).toBeInTheDocument();
  });

  it('klaviatura: 3 — 9 katak, 7 — 1+7', async () => {
    renderWall();
    await loaded();
    fireEvent.keyDown(window, { key: '3' });
    expect(cells()).toHaveLength(9);
    fireEvent.keyDown(window, { key: '7' });
    expect(cells()).toHaveLength(8);
  });

  it("ro'yxat rejimida 25 katakda jonli pleyerlar chegaralanadi, qolgani kadr", async () => {
    renderWall();
    await loaded();
    fireEvent.keyDown(window, { key: '5' });
    fireEvent.click(screen.getByRole('button', { name: "Ro'yxat" }));
    expect(cells()).toHaveLength(25);
    // 25 ta kameradan bittasi oflayn: 16 jonli + 8 kadr.
    expect(players()).toHaveLength(WALL_MAX_LIVE);
    expect(screen.getAllByText('KADR')).toHaveLength(24 - WALL_MAX_LIVE);

    // → keyingi sahifa: qolgan 5 ta kamera.
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(players()).toHaveLength(5);
  });

  it('ikki marta bosish — faqat bitta katak (kattalashtirish), Esc — qaytish', async () => {
    renderWall();
    await loadedFlat();
    fireEvent.click(screen.getByTitle(/Kamera 1 —/));
    fireEvent.click(screen.getByTitle(/Kamera 3 —/));
    expect(players()).toHaveLength(2);
    fireEvent.doubleClick(screen.getByRole('gridcell', { name: 'Kamera 3' }));
    expect(cells()).toHaveLength(1);
    expect(players()).toHaveLength(1);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(cells()).toHaveLength(4);
  });

  it('sudrab tashlash kamerani aniq katakka qo‘yadi', async () => {
    renderWall();
    await loaded();
    const target = cells()[3];
    const dataTransfer = {
      types: [DRAG_CAMERA],
      getData: (type: string) => (type === DRAG_CAMERA ? 'cam-5' : ''),
      dropEffect: 'none',
    };
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    expect(within(cells()[3]).getByText('Kamera 5')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('videowall-current') ?? '{}').tiles).toEqual([null, null, null, 'cam-5']);
  });

  it('yon panel bino → qavat → kamera bo‘yicha yuradi', async () => {
    renderWall();
    await loaded();
    // Yuqori daraja — binolar.
    expect(screen.getByText('2 ta bino · binoni tanlang')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /1-Bino/ }));

    // Bino ichida — qavatlar.
    expect(screen.getByText('3 ta qavat · qavatni tanlang')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /2-qavat/ }));

    // Qavat ichida — faqat o'sha qavat kameralari.
    fireEvent.click(screen.getByTitle(/Kamera 2 —/));
    expect(screen.getByTitle(/Kamera 5 —/)).toBeInTheDocument();
    expect(screen.queryByTitle(/Kamera 3 —/)).not.toBeInTheDocument();

    // Nom bo'yicha qidiruv daraxt darajasidan qat'i nazar ishlaydi.
    fireEvent.click(screen.getByRole('button', { name: 'Barcha binolar' }));
    fireEvent.change(screen.getByLabelText('Kameralarni qidirish'), { target: { value: 'Kamera 30' } });
    expect(screen.getByTitle(/Kamera 30 —/)).toBeInTheDocument();
    expect(screen.queryByTitle(/Kamera 3 —/)).not.toBeInTheDocument();
  });

  it("eski «Bino bo'yicha» havolasi (?kamera=&q=) devorga tushadi", async () => {
    renderWall('/videodevor?tab=binolar&bino=b1&qavat=2&kamera=cam-7&q=Kamera%207');
    await loaded();
    // Kamera devorga qo'yildi va yon panel qidiruvi saqlandi.
    await waitFor(() => expect(players()).toHaveLength(1));
    expect(players()[0]).toHaveAttribute('data-url', cameras[6].streamUrl);
    expect(screen.getByLabelText('Kameralarni qidirish')).toHaveValue('Kamera 7');
  });

  it("sozlamalarda o'chirilgan kamera katakdan olib tashlanadi", async () => {
    localStorage.setItem('videowall-current', JSON.stringify({ layout: '2x2', tiles: ['cam-1', 'cam-2', null, null] }));
    renderWall();
    await loaded();
    expect(within(cells()[0]).getByText('Kamera 1')).toBeInTheDocument();

    // cam-1 sozlamalarda o'chirildi — ro'yxatni yangilaymiz.
    feed = async () => cameras.filter((camera) => camera.id !== 'cam-1');
    fireEvent.click(screen.getByLabelText("Ro'yxatni yangilash"));

    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem('videowall-current') ?? '{}').tiles).toEqual([null, 'cam-2', null, null]),
    );
    expect(screen.queryByText('Kamera 1')).not.toBeInTheDocument();
  });

  it("ro'yxat kelmasa yoki bo'sh bo'lsa devor bo'shab qolmaydi", async () => {
    localStorage.setItem('videowall-current', JSON.stringify({ layout: '2x2', tiles: ['cam-1', 'cam-2', null, null] }));
    renderWall();
    await loaded();

    // 1) Tarmoq xatosi — kataklar joyida qoladi, xato ko'rsatiladi.
    feed = async () => Promise.reject(new Error('tarmoq'));
    fireEvent.click(screen.getByLabelText("Ro'yxatni yangilash"));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/yuklab bo'lmadi/i));
    expect(JSON.parse(localStorage.getItem('videowall-current') ?? '{}').tiles).toEqual(['cam-1', 'cam-2', null, null]);

    // 2) Bo'sh javob ham "hamma kamera o'chirilgan" degani emas.
    feed = async () => [];
    fireEvent.click(screen.getByLabelText("Ro'yxatni yangilash"));
    await waitFor(() => expect(screen.getByText(/^0 ta ·/)).toBeInTheDocument());
    expect(JSON.parse(localStorage.getItem('videowall-current') ?? '{}').tiles).toEqual(['cam-1', 'cam-2', null, null]);
  });

  it("«Yangilash» tugmasi kutish holatini ko'rsatadi va ro'yxatni yangilaydi", async () => {
    renderWall();
    await loaded();
    const button = screen.getByLabelText("Ro'yxatni yangilash");
    expect(button).not.toBeDisabled();

    let release: (list: CameraFeed[]) => void = () => {};
    feed = () => new Promise<CameraFeed[]>((resolve) => { release = resolve; });
    fireEvent.click(button);

    // Bosildi — tugma kutish holatida (ilgari hech narsa o'zgarmasdi).
    await waitFor(() => expect(screen.getByLabelText("Ro'yxatni yangilash")).toBeDisabled());

    await act(async () => {
      release(cameras.slice(0, 3));
    });
    await waitFor(() => expect(screen.getByText(/^3 ta ·/)).toBeInTheDocument());
    expect(screen.getByLabelText("Ro'yxatni yangilash")).not.toBeDisabled();
  });

  it("keyin kelgan ?kamera= havolasi ham devorga tushadi va manzildan o'chadi", async () => {
    renderWall('/videodevor', <LinkLike to="/videodevor?kamera=cam-9" label="Havola" />);
    await loaded();
    expect(players()).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Havola' }));
    await waitFor(() => expect(players()).toHaveLength(1));
    expect(players()[0]).toHaveAttribute('data-url', cameras[8].streamUrl);

    // Havola ishlatilgach parametr manzilda qolmaydi — qo'lda yig'ilgan
    // kataklar "orqaga"/qayta renderda o'z-o'zidan o'zgarmasin.
    fireEvent.click(screen.getByRole('button', { name: 'Katakdan olib tashlash' }));
    expect(players()).toHaveLength(0);
  });

  it('konsol ramkasi: katak kodi, joy kodi, JONLI yorlig‘i va oqim hisobi', async () => {
    renderWall();
    await loadedFlat();
    fireEvent.click(screen.getByTitle(/Kamera 1 —/));

    const cell = cells()[0];
    expect(within(cell).getByText('CAM-001')).toBeInTheDocument();
    expect(within(cell).getByText('B1·Q1')).toBeInTheDocument();
    // "JONLI" faqat oqim rostdan o'ynayotganda.
    expect(within(cell).getByText('JONLI')).toBeInTheDocument();
    // Vaqt tamg'asi (Toshkent, soniyalar bilan).
    expect(within(cell).getByText(/^\d{2}:\d{2}:\d{2}$/)).toBeInTheDocument();

    // Yuqori chiziq: jonli oqim / ro'yxatdagi kamera, kataklar soni.
    expect(screen.getByText('1/30')).toBeInTheDocument();
    expect(screen.getByText('4/4')).toBeInTheDocument();

    // Oflayn katakda "JONLI" chiqmaydi.
    fireEvent.click(screen.getByTitle(/Kamera 2 —/));
    expect(within(cells()[1]).queryByText('JONLI')).not.toBeInTheDocument();
    expect(within(cells()[1]).getByText('OFLAYN')).toBeInTheDocument();
  });

  it("ko'rinishni saqlaydi va localStorage'ga yozadi", async () => {
    renderWall();
    await loadedFlat();
    fireEvent.click(screen.getByTitle(/Kamera 4 —/));
    fireEvent.click(screen.getByTitle("Saqlangan ko'rinishlar"));
    fireEvent.change(screen.getByLabelText(/yangi ko'rinish sifatida saqlash/i), { target: { value: 'Kirishlar' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Saqlash$/ }));
    });
    const saved = JSON.parse(localStorage.getItem('videowall-views') ?? '[]');
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ name: 'Kirishlar', layout: '2x2', tiles: ['cam-4', null, null, null] });
  });
});
