import { useEffect, useRef, useState } from 'react';
import { useAuth } from './auth';
import { config, isBackendConfigured } from './config';
import type { AIEvent, EventStatus } from '../types';

export type LiveEventHandler = (event: AIEvent) => void;

/** Bir nechta hodisa birdan ko'rib chiqilganda keladigan yig'ma xabar
 *  (POST /api/events/review-bulk). Hodisa emas — shuning uchun alohida
 *  ishlovchiga boradi: aks holda "yangi hodisa" hisoblagichi oshib ketardi. */
export interface LiveReviewMessage {
  kind: 'events_reviewed';
  ids: string[];
  status: Exclude<EventStatus, 'yangi'>;
  reviewedBy?: string | null;
}

export type LiveReviewHandler = (message: LiveReviewMessage) => void;

/** Kunning birinchi davomat qaydi (app/jobs/attendance_ai.py
 *  _announce_attendance). Hodisa emas — "yangi hodisa" hisoblagichiga
 *  tushmasligi kerak, shuning uchun alohida ishlovchiga boradi. */
export interface LiveAttendanceMessage {
  kind: 'attendance_recorded';
  personId: string;
  fullName: string | null;
  personType: 'talaba' | 'xodim' | null;
  group: string | null;
  status: 'keldi' | 'kech_keldi';
  checkIn: string | null;
  date: string;
  camera: string | null;
}

export type LiveAttendanceHandler = (message: LiveAttendanceMessage) => void;

interface SocketHandlers {
  onEvent?: LiveEventHandler;
  onReviewed?: LiveReviewHandler;
  onAttendance?: LiveAttendanceHandler;
}

/** Birinchi qayta urinish — tezda (server bir soniyaga o'chib yonganda
 *  operator hech narsa sezmasligi kerak). */
export const RECONNECT_BASE_MS = 1_000;
/** Kutishning yuqori chegarasi. Bunisiz: server bir necha daqiqa
 *  o'chgan bo'lsa, har ochiq ekran (devor ekrani kun bo'yi ochiq turadi)
 *  har 3 soniyada yangi ulanish so'rardi — server ko'tarilishi bilan
 *  o'nlab ekrandan sekundiga o'nlab ulanish "bo'roni" kelardi. */
export const RECONNECT_MAX_MS = 30_000;

/** Kutish vaqti: ikki barobardan oshib boradi, chegaragacha; ustiga
 *  tasodifiy qo'shimcha — hamma ekran bir vaqtda urinmasin. */
export function reconnectDelay(attempt: number, random = Math.random): number {
  const base = Math.min(RECONNECT_BASE_MS * 2 ** Math.max(0, attempt - 1), RECONNECT_MAX_MS);
  return Math.round(base * (0.8 + random() * 0.4));
}

/** Jonli ulanish holati — foydalanuvchi ekranda ko'radi.
 *  'off' — jonli yangilanish umuman yoqilmagan (backend/token yo'q);
 *  'connecting' — ulanmoqda yoki qayta urinmoqda;
 *  'live' — ulangan; 'paused' — uzilgan, qayta urinmaydi (rad etilgan). */
export type LiveStatus = 'off' | 'connecting' | 'live' | 'paused';

/** Server ulanishni rad etgan kodlar (app/routers/events.py): token
 * yaroqsiz (4401) yoki hodisalarni ko'rish huquqi yo'q (4403). Bularda
 * qayta ulanish ma'nosiz — xuddi shu token bilan javob o'zgarmaydi.
 * Sessiya tugagani HTTP so'rovlaridagi 401 orqali alohida aniqlanadi. */
export const WS_REJECTED_CODES: ReadonlySet<number> = new Set([4401, 4403]);

/**
 * Haqiqiy backend'ga /ws/events orqali ulanadi (app/routers/events.py) —
 * yangi AI hodisa yaratilganda yoki ko'rib chiqilganda backend shu ulanish
 * orqali darhol xabar yuboradi. Token query param orqali uzatiladi, chunki
 * brauzer WebSocket API'si maxsus header o'rnatishga imkon bermaydi.
 * Ulanish uzilsa avtomatik qayta urinadi (masalan server qayta ishga tushsa).
 */
function subscribeWebSocket(token: string, handlers: SocketHandlers, onStatus?: (status: LiveStatus) => void): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let cancelled = false;
  let attempt = 0;

  const setStatus = (status: LiveStatus) => {
    if (!cancelled) onStatus?.(status);
  };

  function connect() {
    if (cancelled) return;
    setStatus('connecting');
    const url = `${config.realtimeUrl}?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(url);

    socket.onopen = () => {
      attempt = 0;
      setStatus('live');
    };

    socket.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data && data.kind === 'events_reviewed') {
          handlers.onReviewed?.(data as LiveReviewMessage);
          return;
        }
        if (data && data.kind === 'attendance_recorded') {
          handlers.onAttendance?.(data as LiveAttendanceMessage);
          return;
        }
        handlers.onEvent?.(data as AIEvent);
      } catch {
        /* JSON bo'lmagan xabar — e'tiborsiz qoldiriladi */
      }
    };

    socket.onclose = (e) => {
      if (cancelled) return;
      // Server ATAYLAB rad etdi (token yaroqsiz / huquq yo'q) — xuddi shu
      // token bilan qayta urinish javobni o'zgartirmaydi, faqat shovqin.
      if (WS_REJECTED_CODES.has(e.code)) {
        setStatus('paused');
        return;
      }
      attempt += 1;
      setStatus('connecting');
      reconnectTimer = window.setTimeout(connect, reconnectDelay(attempt));
    };
  }

  connect();

  return () => {
    cancelled = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    // Tozalashdan keyin ishlovchilar chaqirilmasin: yopilayotgan eski
    // ulanishning `onclose`'i yangi taymer qo'yib, ulanish "bo'roni"
    // yasardi (tez-tez token yangilanganda — har yangilanishda bittadan
    // boqimsiz qolgan ulanish).
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
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
export function useLiveEvents(onEvent: LiveEventHandler, enabled = true, onReviewed?: LiveReviewHandler): LiveStatus {
  const { token } = useAuth();
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const reviewRef = useRef(onReviewed);
  reviewRef.current = onReviewed;
  const [status, setStatus] = useState<LiveStatus>('off');

  useEffect(() => {
    if (!enabled || !isBackendConfigured || !config.realtimeUrl || !token) {
      setStatus('off');
      return;
    }
    return subscribeWebSocket(
      token,
      {
        onEvent: (event) => handlerRef.current(event),
        onReviewed: (message) => reviewRef.current?.(message),
      },
      setStatus,
    );
  }, [enabled, token]);

  return status;
}

/** Yangi davomat qaydlari — davomat sahifasi o'zi yangilanishi uchun. */
export function useLiveAttendance(onAttendance: LiveAttendanceHandler, enabled = true) {
  const { token } = useAuth();
  const handlerRef = useRef(onAttendance);
  handlerRef.current = onAttendance;

  useEffect(() => {
    if (!enabled) return;
    if (!isBackendConfigured || !config.realtimeUrl || !token) return;
    return subscribeWebSocket(token, {
      onAttendance: (message) => handlerRef.current(message),
    });
  }, [enabled, token]);
}
