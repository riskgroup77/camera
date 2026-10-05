import type { Nvr, NvrInput } from './videoAnalysisApi';

export interface NvrForm {
  name: string;
  kind: 'hikvision' | 'fayl';
  ip: string;
  httpPort: string;
  rtspPort: string;
  username: string;
  password: string;
  stream: 'main' | 'sub';
  fetchMode: 'download' | 'rtsp';
  maxStreams: string;
  localTime: boolean;
  basePath: string;
  enabled: boolean;
}

export const EMPTY_NVR_FORM: NvrForm = {
  name: '',
  kind: 'hikvision',
  ip: '',
  httpPort: '80',
  rtspPort: '554',
  username: 'admin',
  password: '',
  stream: 'main',
  fetchMode: 'download',
  maxStreams: '8',
  localTime: true,
  basePath: '',
  enabled: true,
};

export function nvrToForm(nvr: Nvr): NvrForm {
  return {
    name: nvr.name,
    kind: nvr.kind,
    ip: nvr.ip ?? '',
    httpPort: String(nvr.httpPort),
    rtspPort: String(nvr.rtspPort),
    username: nvr.username ?? '',
    password: '',
    stream: nvr.stream,
    fetchMode: nvr.fetchMode,
    maxStreams: String(nvr.maxStreams),
    localTime: nvr.localTime,
    basePath: nvr.basePath ?? '',
    enabled: nvr.enabled,
  };
}

const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const HOST = /^[a-zA-Z0-9.-]{1,64}$/;

function port(value: string): number | null {
  if (!/^\d{1,5}$/.test(value.trim())) return null;
  const n = Number(value);
  return n >= 1 && n <= 65535 ? n : null;
}

export function validateNvrForm(form: NvrForm): Partial<Record<keyof NvrForm, string>> {
  const errors: Partial<Record<keyof NvrForm, string>> = {};
  if (!form.name.trim()) errors.name = 'Nomini kiriting';
  if (form.kind === 'hikvision') {
    const ip = form.ip.trim();
    if (!ip) errors.ip = 'IP manzil kerak';
    else if (/^[\d.]+$/.test(ip) ? !IPV4.test(ip) : !HOST.test(ip)) errors.ip = "IP manzil noto'g'ri";
    if (port(form.httpPort) === null) errors.httpPort = "Port 1–65535";
    if (port(form.rtspPort) === null) errors.rtspPort = "Port 1–65535";
  } else if (!form.basePath.trim()) {
    errors.basePath = 'Papka yo‘lini kiriting';
  }
  const streams = Number(form.maxStreams);
  if (!Number.isInteger(streams) || streams < 1 || streams > 64) errors.maxStreams = '1–64';
  return errors;
}

export function buildNvrPayload(form: NvrForm, isEdit: boolean): NvrInput {
  const payload: NvrInput = {
    name: form.name.trim(),
    kind: form.kind,
    maxStreams: Number(form.maxStreams),
    enabled: form.enabled,
  };
  if (form.kind === 'hikvision') {
    payload.ip = form.ip.trim();
    payload.httpPort = Number(form.httpPort);
    payload.rtspPort = Number(form.rtspPort);
    payload.username = form.username.trim() || null;
    payload.stream = form.stream;
    payload.fetchMode = form.fetchMode;
    payload.localTime = form.localTime;
    // Tahrirlashda bo'sh parol — saqlangani o'zgarmaydi.
    if (form.password || !isEdit) payload.password = form.password || null;
  } else {
    payload.basePath = form.basePath.trim();
  }
  return payload;
}
