import { describe, expect, it } from 'vitest';
import {
  UNKNOWN_CAMERA_CODE,
  buildCameraCodes,
  cameraCode,
  cameraPlaceCode,
  formatCameraCode,
} from './cameraCode';
import { formatWallDate, formatWallTime } from './wallClock';

describe('formatCameraCode', () => {
  it("o'rindan uch xonali kod yasaydi", () => {
    expect(formatCameraCode(1)).toBe('CAM-001');
    expect(formatCameraCode(84)).toBe('CAM-084');
    expect(formatCameraCode(1234)).toBe('CAM-1234');
  });

  it("noto'g'ri o'rin uchun noma'lum kod", () => {
    expect(formatCameraCode(0)).toBe(UNKNOWN_CAMERA_CODE);
    expect(formatCameraCode(Number.NaN)).toBe(UNKNOWN_CAMERA_CODE);
  });
});

describe('buildCameraCodes', () => {
  it('id bo‘yicha tabiiy tartibda raqamlaydi (cam-2 < cam-10)', () => {
    const codes = buildCameraCodes([{ id: 'cam-10' }, { id: 'cam-2' }, { id: 'cam-1' }]);
    expect(codes.get('cam-1')).toBe('CAM-001');
    expect(codes.get('cam-2')).toBe('CAM-002');
    expect(codes.get('cam-10')).toBe('CAM-003');
  });

  it("ro'yxat tartibi o'zgarsa ham kod o'zgarmaydi", () => {
    const a = buildCameraCodes([{ id: 'b' }, { id: 'a' }, { id: 'c' }]);
    const b = buildCameraCodes([{ id: 'c' }, { id: 'b' }, { id: 'a' }]);
    expect([...a]).toEqual([...b]);
  });

  it('takroriy id bir marta hisoblanadi', () => {
    const codes = buildCameraCodes([{ id: 'a' }, { id: 'a' }, { id: 'b' }]);
    expect(codes.size).toBe(2);
    expect(codes.get('b')).toBe('CAM-002');
  });

  it("jadvalda yo'q kamera — noma'lum kod", () => {
    const codes = buildCameraCodes([{ id: 'a' }]);
    expect(cameraCode(codes, 'a')).toBe('CAM-001');
    expect(cameraCode(codes, 'yoq')).toBe(UNKNOWN_CAMERA_CODE);
    expect(cameraCode(codes, null)).toBe(UNKNOWN_CAMERA_CODE);
  });
});

describe('cameraPlaceCode', () => {
  it('bino sonini va qavatni oladi', () => {
    expect(cameraPlaceCode({ building: '2-Bino', floor: 3 })).toBe('B2·Q3');
    expect(cameraPlaceCode({ building: '1-Bino', floor: 0 })).toBe('B1·Q0');
  });

  it('bino nomida son bo‘lmasa birinchi harf ishlatiladi', () => {
    expect(cameraPlaceCode({ building: 'Asosiy korpus', floor: 1 })).toBe('BA·Q1');
  });

  it("ma'lumot bo'lmasa hech narsa o'ylab topilmaydi", () => {
    expect(cameraPlaceCode({ building: '', floor: null })).toBe('');
    expect(cameraPlaceCode({ building: '  ', floor: 2 })).toBe('Q2');
    expect(cameraPlaceCode({ building: '3-Bino' })).toBe('B3');
    expect(cameraPlaceCode(null)).toBe('');
  });
});

describe('wallClock formatlari', () => {
  it('Toshkent vaqtini soniyalar bilan beradi', () => {
    expect(formatWallTime(new Date('2024-03-01T07:00:00Z'))).toBe('12:00:00');
    expect(formatWallTime(new Date('2024-03-01T19:04:07Z'))).toBe('00:04:07');
  });

  it('sanani nuqtali ko‘rinishda beradi', () => {
    expect(formatWallDate(new Date('2024-03-01T07:00:00Z'))).toBe('01.03.2024');
  });
});
