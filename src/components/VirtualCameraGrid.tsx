import CameraCard from './CameraCard';
import {
  camerasForLayout,
  gridColsClass,
  shouldPlayStream,
  type GridLayoutMode,
  useStreamVisibility,
  wallLimit,
} from '../lib/virtualCameraGrid';
import type { CameraFeed } from '../types';

export default function VirtualCameraGrid({
  cameras,
  layoutMode,
  onSelect,
}: {
  cameras: CameraFeed[];
  layoutMode: GridLayoutMode;
  onSelect: (camera: CameraFeed) => void;
}) {
  const displayed = camerasForLayout(cameras, layoutMode);
  const wall = wallLimit(layoutMode);
  // Devor rejimida (wall !== null) foydalanuvchi aynan shu N ta kamerani
  // bir vaqtda ko'rishni tanlagan — ular hech qachon navbatga (max 8
  // parallel) qo'yilmasligi kerak, aks holda 9/16 tadan ortig'i abadiy
  // "yuklanmoqda" holatida qolib ketadi (streamLoadQueue.ts'ga qarang).
  const isWallMode = wall !== null;
  const ids = displayed.map((c) => c.id);
  const { setRef, visibleIds } = useStreamVisibility(ids);

  return (
    <div className={`grid gap-4 ${gridColsClass(layoutMode)}`}>
      {displayed.map((camera, index) => {
        const playStream = shouldPlayStream(camera, wall, visibleIds);
        // Ulanish so'rovlarining bir zumda "toshqin" bo'lib ketishini
        // oldini olish uchun kichik bosqichma-bosqich kechikish — avval
        // 500ms/kamera (30-kamera uchun 15 soniya!) edi, endi eng ko'pi
        // bilan ~1.5s.
        const streamStartDelayMs = playStream ? Math.min(index, 10) * 150 : 0;
        return (
          <div key={camera.id} ref={setRef(camera.id)} data-camera-id={camera.id}>
            <CameraCard
              camera={camera}
              onClick={() => onSelect(camera)}
              playStream={playStream}
              streamStartDelayMs={streamStartDelayMs}
              priority={isWallMode}
            />
          </div>
        );
      })}
    </div>
  );
}
