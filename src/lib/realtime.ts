import { useEffect, useRef } from 'react';
import { cameraConfigs } from '../mock/admin';
import { useAuth } from './auth';
import { config, isBackendConfigured } from './config';
import type { AIEvent } from '../types';

export type LiveEventHandler = (event: AIEvent) => void;

const SIM_TEMPLATES: {
  moduleCode: number;
  moduleName: string;
  group: AIEvent['group'];
  severity: AIEvent['severity'];
  personPool?: string[];
}[] = [
  { moduleCode: 1, moduleName: 'Notanish/begona shaxsni aniqlash', group: 'A', severity: 'yuqori' },
  { moduleCode: 8, moduleName: 'Darsga kechikish', group: 'B', severity: "o'rta", personPool: ['Rashidov U.', 'Normatova X.', 'Mirzayev T.'] },
  { moduleCode: 10, moduleName: 'Oq xalat kiyilganligi', group: 'C', severity: 'past', personPool: ['Holiqova S.', 'Qodirov A.'] },
  { moduleCode: 20, moduleName: 'Talabaning uxlab qolishi', group: 'E', severity: "o'rta", personPool: ['Sultonova M.', 'Botirov J.'] },
];

let counter = 0;

function synthesizeEvent(): AIEvent {
  counter += 1;
  const template = SIM_TEMPLATES[counter % SIM_TEMPLATES.length];
  const camera = cameraConfigs[counter % cameraConfigs.length];
  const now = new Date();
  const timestamp = `${now.toISOString().slice(0, 10)} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  return {
    id: `ev-live-${Date.now()}-${counter}`,
    timestamp,
    cameraId: camera.id,
    cameraName: camera.name,
    building: camera.building,
    moduleCode: template.moduleCode,
    moduleName: template.moduleName,
    group: template.group,
    confidence: 70 + ((counter * 5) % 29),
    severity: template.severity,
    status: 'yangi',
    personName: template.personPool?.[counter % template.personPool.length],
  };
}

const SIMULATION_INTERVAL_MS = 25_000;
const RECONNECT_DELAY_MS = 3_000;

function subscribeSimulated(onEvent: LiveEventHandler): () => void {
  const intervalId = window.setInterval(() => {
    onEvent(synthesizeEvent());
  }, SIMULATION_INTERVAL_MS);
  return () => window.clearInterval(intervalId);
}

/**
 * Haqiqiy backend'ga /ws/events orqali ulanadi (app/routers/events.py) —
 * yangi AI hodisa yaratilganda yoki ko'rib chiqilganda backend shu ulanish
 * orqali darhol xabar yuboradi. Token query param orqali uzatiladi, chunki
 * brauzer WebSocket API'si maxsus header o'rnatishga imkon bermaydi.
 * Ulanish uzilsa avtomatik qayta urinadi (masalan server qayta ishga tushsa).
 */
function subscribeWebSocket(token: string, onEvent: LiveEventHandler): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let cancelled = false;

  function connect() {
    if (cancelled) return;
    const url = `${config.realtimeUrl}?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(url);

    socket.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data) as AIEvent);
      } catch {
        /* JSON bo'lmagan xabar — e'tiborsiz qoldiriladi */
      }
    };

    socket.onclose = () => {
      if (cancelled) return;
      reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
    };
  }

  connect();

  return () => {
    cancelled = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    socket?.close();
  };
}

export function useLiveEvents(onEvent: LiveEventHandler, enabled = true) {
  const { token } = useAuth();
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;
    if (isBackendConfigured && config.realtimeUrl && token) {
      return subscribeWebSocket(token, (event) => handlerRef.current(event));
    }
    return subscribeSimulated((event) => handlerRef.current(event));
  }, [enabled, token]);
}
