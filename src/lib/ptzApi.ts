import { api } from './apiClient';
import type { PtzProtocol } from '../types';

/** PTZ boshqaruvi — backend app/routers/ptz.py. Barcha chaqiruvlar
 * `controlPtz` huquqini talab qiladi (tekshiruv — `manageCameras` ham). */

export interface PtzStatus {
  cameraId: string;
  enabled: boolean;
  protocol: PtzProtocol | null;
  onvifPort: number | null;
}

export interface PtzPreset {
  token: string;
  name: string;
}

export interface PtzVelocity {
  /** -1..1: manfiy — chapga, musbat — o'ngga. */
  pan: number;
  /** -1..1: manfiy — pastga, musbat — yuqoriga. */
  tilt: number;
  /** -1..1: manfiy — uzoqlashtirish, musbat — yaqinlashtirish. */
  zoom: number;
}

export interface PtzProbeResult {
  success: boolean;
  message: string;
  protocol: PtzProtocol | null;
  reachable: boolean;
  authenticated: boolean;
  ptzSupported: boolean;
  presetsSupported: boolean;
  presetCount: number | null;
  deviceInfo: string | null;
  latencyMs: number | null;
  tried: PtzProtocol[];
}

export interface PtzProbeOverrides {
  protocol?: PtzProtocol | null;
  onvifPort?: number | null;
  username?: string | null;
  password?: string | null;
}

const base = (cameraId: string) => `/api/cameras/${encodeURIComponent(cameraId)}/ptz`;

/** Tugma bosib turilganda harakat shu vaqtdan keyin serverda o'zi
 * to'xtaydi — brauzer "to'xtash"ni yubora olmasa ham (tarmoq uzildi,
 * varaq yopildi) kamera aylanib qolmaydi. Panel buni KEEPALIVE_MS da
 * yangilab turadi. */
export const PTZ_HOLD_DURATION_MS = 2000;
export const PTZ_KEEPALIVE_MS = 1200;

export function clampVelocity(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(-1, Math.min(1, Math.round(value * 1000) / 1000));
}

export const ptzApi = {
  status: (cameraId: string) => api.get<PtzStatus>(base(cameraId)),
  move: (cameraId: string, velocity: PtzVelocity, durationMs: number | null = PTZ_HOLD_DURATION_MS) =>
    api.post<void>(`${base(cameraId)}/move`, {
      pan: clampVelocity(velocity.pan),
      tilt: clampVelocity(velocity.tilt),
      zoom: clampVelocity(velocity.zoom),
      durationMs,
    }),
  stop: (cameraId: string) => api.post<void>(`${base(cameraId)}/stop`, {}),
  presets: (cameraId: string) => api.get<PtzPreset[]>(`${base(cameraId)}/presets`),
  gotoPreset: (cameraId: string, token: string) =>
    api.post<void>(`${base(cameraId)}/presets/${encodeURIComponent(token)}/goto`, {}),
  savePreset: (cameraId: string, name: string) => api.post<PtzPreset>(`${base(cameraId)}/presets`, { name }),
  /** Saqlangan kamera: forma qiymatlari (hali saqlanmagan) ustama sifatida. */
  probe: (cameraId: string, overrides: PtzProbeOverrides = {}) =>
    api.post<PtzProbeResult>(`${base(cameraId)}/probe`, overrides),
  /** Hali saqlanmagan kamera ("Yangi kamera qo'shish" formasi). */
  probeUnsaved: (body: { ip: string } & PtzProbeOverrides) =>
    api.post<PtzProbeResult>('/api/cameras/ptz/probe', body),
};

export type PtzCommand = { kind: 'move'; velocity: PtzVelocity } | { kind: 'stop' };

/** Buyruqlar navbati: bir vaqtda kameraga faqat BITTA so'rov ketadi,
 * javob kelguncha kelgan buyruqlardan faqat ENG SO'NGGISI saqlanadi.
 *
 * Nega: operator tugmalarni tez-tez bossa (yoki klaviaturadan yo'nalish
 * almashtirsa) so'rovlar parallel ketib, kameraga teskari tartibda
 * yetishi mumkin — "to'xta" oldin, "chapga" keyin kelsa kamera aylanib
 * qoladi. Navbat tartibni saqlaydi va eskirgan oraliq buyruqlarni
 * tashlab yuboradi (kechikish to'planmaydi). */
export function createPtzCommandQueue(run: (command: PtzCommand) => Promise<void>, onError: (err: unknown) => void) {
  let inflight = false;
  let pending: PtzCommand | null = null;

  async function pump(command: PtzCommand) {
    inflight = true;
    try {
      await run(command);
    } catch (err) {
      onError(err);
    } finally {
      inflight = false;
      const next = pending;
      pending = null;
      if (next) void pump(next);
    }
  }

  return {
    push(command: PtzCommand) {
      if (inflight) {
        pending = command;
        return;
      }
      void pump(command);
    },
    get busy() {
      return inflight;
    },
  };
}
