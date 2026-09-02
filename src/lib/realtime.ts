import { useEffect, useRef } from 'react';
import { useAuth } from './auth';
import { config, isBackendConfigured } from './config';
import type { AIEvent } from '../types';

export type LiveEventHandler = (event: AIEvent) => void;

const RECONNECT_DELAY_MS = 3_000;

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

/**
 * Backend/token bo'lmasa — HECH NARSA qilmaydi.
 *
 * Ilgari bu yerda "simulyatsiya" rejimi bor edi: mock ma'lumotlaridan
 * (src/mock/admin.ts) har 25 soniyada SOXTA AI hodisa yasab, uni haqiqiy
 * hodisa sifatida UI'ga uzatardi. Xavfsizlik tizimida bu qabul qilib
 * bo'lmaydigan xatar — operator ekranda ko'rgan "hodisa" hech qachon
 * o'ylab topilgan bo'lmasligi kerak. Demo ma'lumot kerak bo'lsa, u
 * backend tomonda, ochiq belgilangan holda berilishi lozim.
 */
export function useLiveEvents(onEvent: LiveEventHandler, enabled = true) {
  const { token } = useAuth();
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;
    if (!isBackendConfigured || !config.realtimeUrl || !token) return;
    return subscribeWebSocket(token, (event) => handlerRef.current(event));
  }, [enabled, token]);
}
