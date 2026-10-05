import { describe, expect, it } from 'vitest';
import { TrackTimeline } from './liveTracks';
import { overlayTime, pictureRect } from '../components/FaceDetectionOverlay';
import type { LiveDetectionFrame } from '../types';

function frame(at: number, faces: LiveDetectionFrame['faces']): LiveDetectionFrame {
  return { frameWidth: 1000, frameHeight: 1000, capturedAt: at, faces };
}

const face = (x: number, trackId: number, extra: Partial<LiveDetectionFrame['faces'][number]> = {}) => ({
  bbox: [x, 100, x + 100, 200] as [number, number, number, number],
  asleep: false,
  status: 'notanish' as const,
  trackId,
  ...extra,
});

describe('TrackTimeline', () => {
  it("ikki natija orasida ramkani iz bo'yicha silliq siljitadi", () => {
    const timeline = new TrackTimeline();
    timeline.add([frame(10, [face(0, 1)]), frame(11, [face(200, 1)])]);
    const [box] = timeline.boxesAt(10_500);
    expect(box.box[0]).toBeCloseTo(0.1); // yarim yo'lda: 0 -> 200 px
  });

  it("ism butun iz bo'ylab — video u kadrga yetmasdan oldin ham", () => {
    const timeline = new TrackTimeline();
    timeline.add([
      frame(10, [face(0, 1)]),
      frame(11, [face(50, 1, { status: 'tanildi', personName: 'Aliyev Anvar' })]),
    ]);
    const [box] = timeline.boxesAt(10_100);
    expect(box.status).toBe('tanildi');
    expect(box.name).toBe('Aliyev Anvar');
  });

  it("video birinchi tahlil qilingan kadrga yetmagan bo'lsa hech narsa chizilmaydi", () => {
    const timeline = new TrackTimeline();
    timeline.add([frame(10, [face(0, 1)])]);
    expect(timeline.boxesAt(9_000)).toEqual([]);
  });

  it("oxirgi natijadan keyin qisqa muddat davom etadi, so'ng o'chadi", () => {
    const timeline = new TrackTimeline();
    timeline.add([frame(10, [face(0, 1)]), frame(11, [face(100, 1)])]);
    const [ahead] = timeline.boxesAt(11_500);
    expect(ahead.box[0]).toBeGreaterThan(0.1); // harakat yo'nalishida
    expect(timeline.boxesAt(14_000)).toEqual([]);
  });

  it("keyingi natijada yo'q yuz so'nadi", () => {
    const timeline = new TrackTimeline();
    timeline.add([frame(10, [face(0, 1)]), frame(11, [])]);
    expect(timeline.boxesAt(10_100)[0].opacity).toBeGreaterThan(0.5);
    expect(timeline.boxesAt(10_900)).toEqual([]);
  });

  it('takroriy natija ikki marta qo\'shilmaydi', () => {
    const timeline = new TrackTimeline();
    timeline.add([frame(10, [face(0, 1)])]);
    timeline.add([frame(10, [face(0, 1)]), frame(11, [face(0, 1)])]);
    expect(timeline.size).toBe(2);
  });
});

describe('overlayTime', () => {
  it('video soati bor — tuzatish bilan', () => {
    expect(overlayTime(10_000, 12_000, 500)).toBe(9_500);
  });
  it("soat yo'q yoki juda uzoq — eng so'nggi natija", () => {
    expect(overlayTime(null, 12_000, 0)).toBe(12_000);
    expect(overlayTime(100_000, 12_000, 0)).toBe(12_000);
  });
});

describe('pictureRect', () => {
  it('contain — chetida bo\'sh joy, cover — kesiladi', () => {
    expect(pictureRect(200, 200, 16, 9, 'contain')).toEqual({ x: 0, y: 43.75, w: 200, h: 112.5 });
    const cover = pictureRect(200, 200, 16, 9, 'cover')!;
    expect(cover.h).toBe(200);
    expect(cover.x).toBeLessThan(0);
  });
});
