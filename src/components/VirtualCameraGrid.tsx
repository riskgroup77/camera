import CameraCard from './CameraCard';
import {
  camerasForLayout,
  gridColsClass,
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
  const ids = displayed.map((c) => c.id);
  const { setRef, activeStreamIds } = useStreamVisibility(ids);

  return (
    <div className={`grid gap-4 ${gridColsClass(layoutMode)}`}>
      {displayed.map((camera, index) => {
        const playStream = wall !== null ? index < 8 : activeStreamIds.has(camera.id);
        return (
          <div key={camera.id} ref={setRef(camera.id)} data-camera-id={camera.id}>
            <CameraCard camera={camera} onClick={() => onSelect(camera)} playStream={playStream} />
          </div>
        );
      })}
    </div>
  );
}
