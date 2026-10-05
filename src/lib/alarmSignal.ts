import type { AIEvent } from '../types';

/**
 * Yuqori darajali hodisada operatorni OGOHLANTIRISH: qisqa ovoz va (ruxsat
 * berilgan bo'lsa) ish stoli bildirishnomasi.
 *
 * Xalqaro konsollarda (Milestone, Genetec) signal ovoz va qalqib chiquvchi
 * oyna bilan keladi; bizda faqat qizil nuqta bor edi — boshqa oynada
 * ishlayotgan operator yong'in yoki begona shaxs signalini ko'rmasdi.
 *
 * Sozlama shu brauzerda saqlanadi (har operator o'zi uchun).
 */

const SOUND_KEY = 'alarm-sound';

export function alarmSoundEnabled(): boolean {
  try {
    return localStorage.getItem(SOUND_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function setAlarmSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(SOUND_KEY, on ? 'on' : 'off');
  } catch {
    /* saqlab bo'lmadi — faqat shu seans */
  }
}

/** Signal berilishi kerak bo'lgan hodisa: yuqori daraja, sinov emas, yangi. */
export function isAlarm(event: Pick<AIEvent, 'severity' | 'isTrial' | 'status'>): boolean {
  return event.severity === 'yuqori' && !event.isTrial && (event.status === undefined || event.status === 'yangi');
}

let audio: AudioContext | null = null;

/** Ikki qisqa ton (~0.5 s). Brauzer foydalanuvchi bosmaguncha ovozni
 *  bloklasa — jimgina o'tkazib yuboriladi. */
export function playAlarmTone(): void {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    audio ??= new Ctx();
    const ctx = audio;
    if (ctx.state === 'suspended') void ctx.resume();
    [0, 0.26].forEach((offset, index) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = index === 0 ? 880 : 660;
      const start = ctx.currentTime + offset;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.24);
    });
  } catch {
    /* ovoz — qo'shimcha; xatosi signalni to'xtatmasin */
  }
}

export function desktopNotificationsState(): NotificationPermission | 'unsupported' {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission;
}

export async function requestDesktopNotifications(): Promise<NotificationPermission | 'unsupported'> {
  if (typeof Notification === 'undefined') return 'unsupported';
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

/** Oyna ko'rinmayotgan bo'lsa — ish stoli bildirishnomasi. Bosilsa hodisalar sahifasi. */
function notifyDesktop(event: AIEvent): void {
  if (desktopNotificationsState() !== 'granted' || !document.hidden) return;
  try {
    const note = new Notification(event.moduleName, {
      body: [event.cameraName, event.building].filter(Boolean).join(' · '),
      tag: `event-${event.id}`,
      icon: event.snapshotUrl ?? undefined,
    });
    note.onclick = () => {
      window.focus();
      window.location.assign('/hodisalar');
      note.close();
    };
  } catch {
    /* ba'zi brauzerlar konstruktorni taqiqlaydi (faqat service worker) */
  }
}

// Bir xil hodisa ikki kanaldan (konsol va qobiq) kelsa ham bir marta.
const signalled = new Set<string>();

export function signalAlarm(event: AIEvent & { kind?: string }): boolean {
  // event_updated — mavjud hodisaning holati o'zgargani, yangi signal emas.
  if (event.kind === 'event_updated' || !isAlarm(event) || signalled.has(event.id)) return false;
  signalled.add(event.id);
  if (signalled.size > 500) signalled.clear();
  if (alarmSoundEnabled()) playAlarmTone();
  notifyDesktop(event);
  return true;
}
