import KpiStrip from '../../components/hisobot/KpiStrip';
import { RagLegend, StatusBoard, type BoardItem } from '../../components/hisobot/board';
import TabelView from '../../components/reports/TabelView';
import { IntelPanel } from '../../ui';
import WallTile from '../../components/videowall/WallTile';
import { buildCameraCodes } from '../../components/videowall/cameraCode';
import type { CameraFeed } from '../../types';
import type { TabelDay, TabelPerson, TabelReport } from '../../lib/tabelApi';

const DAYS: TabelDay[] = Array.from({ length: 30 }, (_, i) => {
  const day = i + 1;
  const weekday = (day + 1) % 7; // 2026-09-01 — seshanba
  return { day, weekday, isWorkDay: weekday !== 0 && weekday !== 6, isFuture: day > 19 };
});

const NAMES = [
  'Aliyev Anvar Anvarovich', 'Botirova Dilnoza Baxtiyorovna', 'Nazarov Jasur Olimovich',
  'Sobirov Otabek Rustamovich', 'Karimova Maftuna Shuhratovna', 'Yusupov Sardor Alisherovich',
  'Toshmatova Nilufar Azizovna', 'Ergashev Bekzod Farhodovich',
];

const MARKS = ['+', '+', 'K', '+', '–', '+', '+', 'K'];

const PEOPLE: TabelPerson[] = NAMES.map((fullName, personIndex) => {
  const enrolled = personIndex !== 2;
  const cells = DAYS.map((d) => {
    if (!d.isWorkDay) return { day: d.day, mark: 'D', title: 'dam olish kuni' };
    if (d.isFuture) return { day: d.day, mark: '·', title: 'kun hali kelmagan' };
    if (!enrolled) return { day: d.day, mark: '·', title: "yuzi tizimga kiritilmagan" };
    return { day: d.day, mark: MARKS[(d.day + personIndex) % MARKS.length], title: '08:0' + (d.day % 9) + ' da keldi' };
  });
  return {
    id: 'p' + personIndex, fullName, group: personIndex % 2 ? 'DI-2301' : 'DI-2302', enrolled, cells,
    totals: { present: 0, late: 0, absent: 0, unknown: 0, workDays: 0 },
  };
});

const TABEL: TabelReport = {
  title: 'Davomat tabeli',
  scope: 'Davolash ishi fakulteti, 2-kurs',
  month: '2026-09',
  monthLabel: 'Sentabr 2026',
  days: DAYS,
  people: PEOPLE,
  totals: { people: PEOPLE.length, present: 0, late: 0, absent: 0, unknown: 0, notEnrolled: 1 },
  legend: [],
  note: null,
};

/**
 * FAQAT ISHLAB CHIQISH UCHUN (`import.meta.env.DEV`).
 *
 * Dizaynni brauzerda haqiqiy ko'z bilan tekshirish sahifasi: serverga
 * ham, tizimga kirishga ham bog'liq emas. Ishlab chiqarish yig'masiga
 * tushmaydi (App.tsx dagi shart).
 */

const CAMERAS: CameraFeed[] = [
  { id: 'cam-2', name: 'Bosh kirish — turniket', building: '2-bino', zone: 'Kirish', status: 'live', floor: 1, hasVideo: true },
  { id: 'cam-10', name: 'Dahliz, sharqiy qanot', building: '2-bino', zone: 'Dahliz', status: 'live', floor: 3, hasVideo: true },
  { id: 'cam-11', name: 'Kutubxona zali', building: '1-bino', zone: 'Kutubxona', status: 'live', floor: 2, hasVideo: false },
  { id: 'cam-84', name: 'Hovli, janubiy darvoza', building: '3-bino', zone: 'Perimetr', status: 'offline', floor: null },
];

const NOOP = () => {};

const BOARD: BoardItem[] = [
  { id: 'u1', name: 'Ichki kasalliklar kafedrasi', value: 96.2, unit: '%', detail: '52/54 keldi', headcount: 54 },
  { id: 'u2', name: 'Jarrohlik kafedrasi', value: 91, unit: '%', detail: '41/45 keldi', headcount: 45 },
  { id: 'u3', name: 'Pediatriya kafedrasi', value: 82.4, unit: '%', detail: '28/34 keldi', headcount: 34 },
  { id: 'u4', name: 'Farmakologiya kafedrasi', value: 76, unit: '%', detail: '19/25 keldi', headcount: 25 },
  { id: 'u5', name: "Jamoat salomatligi kafedrasi", value: 61.5, unit: '%', detail: '16/26 keldi', headcount: 26 },
  { id: 'u6', name: 'Xo’jalik bo’limi', value: 48, unit: '%', detail: '12/25 keldi', headcount: 25 },
  { id: 'u7', name: 'Axborot texnologiyalari bo’limi', value: null, unit: '%', detail: "yuzi ro'yxatda yo'q", headcount: 9 },
];

const TILES = [
  { label: 'Umumiy davomat', value: 84.6, unit: '%', hint: '218 kishidan 184 tasi keldi', tone: 'primary' as const },
  { label: "O'z vaqtida", value: 71.1, unit: '%', hint: '155 kishi 08:10 gacha keldi', tone: 'success' as const },
  { label: 'Kech keldi', value: 29, unit: 'ta', hint: "O'rtacha 24 daqiqa kechikish", tone: 'warning' as const },
  { label: 'Kelmadi', value: 34, unit: 'ta', hint: 'Kun davomida kamerada ko’rinmadi', tone: 'danger' as const },
];

export default function PreviewPage() {
  const codes = buildCameraCodes(CAMERAS);
  return (
    <div className="min-h-screen bg-bg p-6">
      <h1 className="intel-micro mb-4 !text-fg">Dizayn ko&apos;rigi — kamera kataklari</h1>
      <div className="grid grid-cols-2 gap-px bg-border" style={{ aspectRatio: '16 / 7' }}>
        {CAMERAS.map((camera, index) => (
          <WallTile
            key={camera.id}
            index={index}
            cameraId={camera.id}
            camera={camera}
            code={codes.get(camera.id)}
            playback={index === 3 ? 'offline' : 'snapshot'}
            style={{}}
            startDelayMs={0}
            selected={index === 0}
            maximized={false}
            editable
            compact={false}
            onSelect={NOOP}
            onToggleMaximize={NOOP}
            onRemove={NOOP}
            onDropCamera={NOOP}
            onDropTile={NOOP}
          />
        ))}
      </div>
      <div className="mt-6 grid grid-cols-2 gap-px bg-border" style={{ aspectRatio: '16 / 7' }}>
        <WallTile
          index={9}
          cameraId={null}
          camera={null}
          playback="empty"
          style={{}}
          startDelayMs={0}
          selected={false}
          maximized={false}
          editable
          compact={false}
          onSelect={NOOP}
          onToggleMaximize={NOOP}
          onRemove={NOOP}
          onDropCamera={NOOP}
          onDropTile={NOOP}
        />
        <WallTile
          index={10}
          cameraId="cam-yoq"
          camera={null}
          playback="offline"
          style={{}}
          startDelayMs={0}
          selected={false}
          maximized={false}
          editable
          compact={false}
          onSelect={NOOP}
          onToggleMaximize={NOOP}
          onRemove={NOOP}
          onDropCamera={NOOP}
          onDropTile={NOOP}
        />
      </div>

      <h1 className="intel-micro mb-4 mt-10 !text-fg">Dizayn ko&apos;rigi — holat taxtasi</h1>
      <div className="flex flex-col gap-3">
        <IntelPanel title="Asosiy ko&apos;rsatkichlar">
          <KpiStrip tiles={TILES} />
        </IntelPanel>
        <IntelPanel title="Bo&apos;linmalar holati" code="7 ta">
          <StatusBoard items={BOARD} onOpen={NOOP} />
          <RagLegend />
        </IntelPanel>
      </div>

      <h1 className="intel-micro mb-4 mt-10 !text-fg">Dizayn ko&apos;rigi — oylik tabel</h1>
      <TabelView data={TABEL} section="talabalar" />
    </div>
  );
}
