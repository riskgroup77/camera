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
  const ids = displayed.map((c) => c.id);
  const { setRef, visibleIds } = useStreamVisibility(ids);

  return (
    <div className={`grid gap-4 ${gridColsClass(layoutMode)}`}>
      {displayed.map((camera, index) => {
        const playStream = shouldPlayStream(camera, wall, visibleIds);
        const streamStartDelayMs = playStream ? Math.min(index, 30) * 500 : 0;
        return (
          <div key={camera.id} ref={setRef(camera.id)} data-camera-id={camera.id}>
            <CameraCard
              camera={camera}
              onClick={() => onSelect(camera)}
              playStream={playStream}
              streamStartDelayMs={streamStartDelayMs}
            />
          </div>
        );
      })}
    </div>
  );
}
