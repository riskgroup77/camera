import { describe, expect, it } from 'vitest';
import { faceLabel } from './FaceDetectionOverlay';
import { scanCounts } from '../console/panels/CamerasPanel';

describe('faceLabel', () => {
  it('tanilgan yuzda ism, notanishda "Notanish"', () => {
    expect(faceLabel('tanildi', 'Aliyev Anvar', false)).toBe('Aliyev Anvar');
    expect(faceLabel('notanish', null, false)).toBe('Notanish');
  });

  it("kichik yuzga yozuv yo'q — u tahlil qilinmagan", () => {
    expect(faceLabel('kichik', null, false)).toBe('');
  });

  it('uxlab qolgan belgisi qo\'shiladi', () => {
    expect(faceLabel('tanildi', 'Aliyev Anvar', true)).toBe('Aliyev Anvar — uxlab qolgan');
  });
});

describe('scanCounts', () => {
  it('holatlar bo\'yicha sanaydi va 4K manbani belgilaydi', () => {
    const counts = scanCounts({
      frameWidth: 3840,
      frameHeight: 2160,
      source: 'asosiy',
      faces: [
        { bbox: [0, 0, 1, 1], asleep: false, status: 'tanildi', personName: 'A' },
        { bbox: [0, 0, 1, 1], asleep: false, status: 'notanish' },
        { bbox: [0, 0, 1, 1], asleep: false, status: 'notanish' },
        { bbox: [0, 0, 1, 1], asleep: false, status: 'kichik' },
      ],
    });
    expect(counts).toEqual({ total: 4, known: 1, unknown: 2, small: 1, hd: true });
  });

  it("eski javobda (status yo'q) ismga qarab ajratadi", () => {
    const counts = scanCounts({ frameWidth: 1, frameHeight: 1, faces: [{ bbox: [0, 0, 1, 1], asleep: false, personName: null }] });
    expect(counts?.unknown).toBe(1);
  });

  it("natija hali kelmagan bo'lsa null", () => {
    expect(scanCounts(null)).toBeNull();
  });
});
