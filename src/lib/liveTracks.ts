import type { DetectedFace, DetectedFaceStatus, LiveDetectionFrame } from '../types';

/**
 * Jonli skaner ramkalarini VIDEONING O'Z VAQTIGA moslash.
 *
 * Muammo: server kadrni ~1 s da bir tahlil qiladi, brauzerdagi video esa
 * 2-4 s orqada keladi. Ilgari eng oxirgi natija hozir ko'rinayotgan kadr
 * ustiga chizilardi — odam tez yursa ramka bo'sh joyda qolardi, odam ko'p
 * bo'lsa ism yonidagi boshqa odamga tushardi.
 *
 * Yechim: har natijada kadr olingan payt (`capturedAt`, server soati)
 * bor, HLS pleylistida esa har kadrning shu soatdagi payti
 * (EXT-X-PROGRAM-DATE-TIME). Ramka videoning AYNAN o'sha paytiga
 * qo'yiladi, ikki natija orasida esa iz raqami (`trackId`) bo'yicha
 * silliq siljitiladi. Video tahlildan orqada bo'lgani uchun keyingi
 * natija odatda allaqachon kelgan bo'ladi — ya'ni bu bashorat emas,
 * ikki haqiqiy o'lchov orasidagi interpolatsiya.
 *
 * Ism esa vaqtga bog'liq emas: iz birorta natijada tanilgan bo'lsa, ismi
 * butun iz bo'ylab ko'rsatiladi (video u kadrga yetib kelmasdan oldin ham).
 */

export interface TrackBox {
  key: string;
  /** Normallashgan [x1, y1, x2, y2] (0..1, kadrga nisbatan). */
  box: [number, number, number, number];
  status: DetectedFaceStatus;
  name: string | null;
  asleep: boolean;
  /** 0..1 — paydo bo'layotgan/yo'qolayotgan ramka shaffofligi. */
  opacity: number;
}

interface Frame {
  at: number; // ms, server soati
  width: number;
  height: number;
  faces: DetectedFace[];
}

/** Ikki natija bundan uzoq bo'lsa, oralig'ida siljitilmaydi (odam yo'qolgan). */
const MAX_GAP_MS = 3500;
/** Oxirgi natijadan keyin ramka shuncha vaqt oldinga davom ettiriladi.
 *  WebRTC videoda (real vaqt) tahlil natijasi doim ~1 s orqada keladi —
 *  ramka shu oraliqni harakat yo'nalishida bosib o'tadi. */
const EXTRAPOLATE_MS = 1500;
/** Oxirgi natijadan keyin ramka shuncha vaqtdan so'ng o'chadi. */
const STALE_MS = 3000;
const KEEP_MS = 15_000;

export class TrackTimeline {
  private frames: Frame[] = [];

  /** Yangi natijalarni qo'shadi (takrorlari tashlanadi). */
  add(items: LiveDetectionFrame[]): void {
    let changed = false;
    for (const item of items) {
      if (item.capturedAt == null || !item.frameWidth || !item.frameHeight) continue;
      const at = item.capturedAt * 1000;
      if (this.frames.some((frame) => Math.abs(frame.at - at) < 1)) continue;
      this.frames.push({ at, width: item.frameWidth, height: item.frameHeight, faces: item.faces });
      changed = true;
    }
    if (!changed) return;
    this.frames.sort((a, b) => a.at - b.at);
    const newest = this.frames[this.frames.length - 1].at;
    this.frames = this.frames.filter((frame) => newest - frame.at <= KEEP_MS);
  }

  clear(): void {
    this.frames = [];
  }

  get newestAt(): number | null {
    return this.frames.length ? this.frames[this.frames.length - 1].at : null;
  }

  get size(): number {
    return this.frames.length;
  }

  /** `t` (ms, server soati) paytidagi ramkalar. */
  boxesAt(t: number): TrackBox[] {
    const frames = this.frames;
    if (!frames.length) return [];
    let index = -1;
    for (let i = 0; i < frames.length; i += 1) {
      if (frames[i].at <= t) index = i;
      else break;
    }
    if (index < 0) return []; // video hali birinchi tahlil qilingan kadrga yetmagan
    const f0 = frames[index];
    const f1 = frames[index + 1];
    const names = this.names();
    const out: TrackBox[] = [];
    const interpolate = f1 !== undefined && f1.at - f0.at <= MAX_GAP_MS;
    const alpha = interpolate ? (t - f0.at) / (f1.at - f0.at) : 0;
    const since = t - f0.at;
    if (!interpolate && since > STALE_MS) return [];

    f0.faces.forEach((face, i) => {
      const a = normalise(face.bbox, f0);
      const key = face.trackId != null ? `t${face.trackId}` : `f${f0.at}-${i}`;
      let box = a;
      let opacity = 1;
      if (interpolate) {
        const next = face.trackId != null ? f1.faces.find((other) => other.trackId === face.trackId) : undefined;
        if (next) box = lerp(a, normalise(next.bbox, f1), alpha);
        else opacity = alpha < 0.5 ? 1 - alpha * 2 : 0; // keyingi kadrda yo'q — so'nadi
      } else {
        const velocity = this.velocity(index, face);
        const ahead = Math.min(since, EXTRAPOLATE_MS);
        if (velocity) box = shift(a, velocity, ahead);
        opacity = since > STALE_MS - 500 ? Math.max(0, (STALE_MS - since) / 500) : 1;
      }
      if (opacity <= 0.02) return;
      const known = face.trackId != null ? names.get(face.trackId) : undefined;
      const status: DetectedFaceStatus = known ? 'tanildi' : face.status ?? (face.personName ? 'tanildi' : 'notanish');
      out.push({
        key,
        box,
        status,
        name: known ?? face.personName ?? null,
        asleep: face.asleep,
        opacity,
      });
    });
    return out;
  }

  /** Iz -> eng so'nggi tanilgan ismi (barcha natijalar bo'yicha). */
  private names(): Map<number, string> {
    const names = new Map<number, string>();
    for (const frame of this.frames) {
      for (const face of frame.faces) {
        if (face.trackId != null && face.personName && (face.status ?? 'tanildi') === 'tanildi') {
          names.set(face.trackId, face.personName);
        }
      }
    }
    return names;
  }

  /** Iz tezligi (normallashgan birlik / ms) — oldingi natijadan. */
  private velocity(index: number, face: DetectedFace): [number, number] | null {
    if (face.trackId == null || index < 1) return null;
    const current = this.frames[index];
    const previous = this.frames[index - 1];
    const dt = current.at - previous.at;
    if (dt <= 0 || dt > MAX_GAP_MS) return null;
    const before = previous.faces.find((other) => other.trackId === face.trackId);
    if (!before) return null;
    const [ax, ay] = centre(normalise(before.bbox, previous));
    const [bx, by] = centre(normalise(face.bbox, current));
    return [(bx - ax) / dt, (by - ay) / dt];
  }
}

function normalise(bbox: DetectedFace['bbox'], frame: { width: number; height: number }): [number, number, number, number] {
  return [bbox[0] / frame.width, bbox[1] / frame.height, bbox[2] / frame.width, bbox[3] / frame.height];
}

function lerp(a: number[], b: number[], t: number): [number, number, number, number] {
  const k = Math.min(1, Math.max(0, t));
  return [0, 1, 2, 3].map((i) => a[i] + (b[i] - a[i]) * k) as [number, number, number, number];
}

function centre(box: number[]): [number, number] {
  return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
}

function shift(box: number[], velocity: [number, number], ms: number): [number, number, number, number] {
  const dx = velocity[0] * ms;
  const dy = velocity[1] * ms;
  return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy];
}
