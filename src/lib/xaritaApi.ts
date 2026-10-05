import { api, type CallOptions } from './apiClient';

/** Xarita — qavat rejasi ustida kameralar (camera-api/app/routers/xarita.py). */

export type MapCameraStatus = 'online' | 'novideo' | 'offline';

export interface MapFloor {
  floor: number;
  hasPlan: boolean;
  cameraCount: number;
  placedCount: number;
}

export interface MapBuilding {
  id: string;
  name: string;
  floors: MapFloor[];
}

export interface MapPlan {
  imageUrl: string | null;
  width: number;
  height: number;
  updatedAt: string;
}

export interface MapCamera {
  id: string;
  name: string;
  zone: string;
  status: MapCameraStatus;
  /** Nisbiy koordinata 0..1; null — xaritaga qo'yilmagan. */
  x: number | null;
  y: number | null;
  /** Qarash yo'nalishi, gradus: 0 — yuqoriga, soat mili bo'yicha. */
  angle: number | null;
  fov: number;
  openEvents: number;
  /** So'nggi 10 daqiqada shu kamerada tanilgan turli odamlar. */
  peopleNow?: number;
  streamUrl: string | null;
  /** false — kamera hali biror qavatga biriktirilmagan. */
  assigned: boolean;
}

export interface MapFloorView {
  buildingId: string;
  buildingName: string;
  floor: number;
  plan: MapPlan | null;
  cameras: MapCamera[];
  /** Qavatsiz kameralar — faqat tahrir huquqi borlarga. */
  candidates: MapCamera[];
}

export interface MapPlacement {
  x: number | null;
  y: number | null;
  angle?: number | null;
  fov?: number | null;
  buildingId?: string;
  floor?: number;
}

export function getMapBuildings(opts: CallOptions = {}): Promise<MapBuilding[]> {
  return api.get<MapBuilding[]>('/api/xarita/binolar', undefined, opts);
}

export function getMapFloor(buildingId: string, floor: number, opts: CallOptions = {}): Promise<MapFloorView> {
  return api.get<MapFloorView>(`/api/xarita/${encodeURIComponent(buildingId)}/${floor}`, undefined, opts);
}

export function uploadMapImage(buildingId: string, floor: number, file: File): Promise<MapPlan> {
  const form = new FormData();
  form.append('file', file);
  return api.putForm<MapPlan>(`/api/xarita/${encodeURIComponent(buildingId)}/${floor}/rasm`, form);
}

export function placeCamera(cameraId: string, body: MapPlacement): Promise<MapCamera> {
  return api.put<MapCamera>(`/api/xarita/kamera/${encodeURIComponent(cameraId)}/joy`, body);
}
