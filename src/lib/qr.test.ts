import { describe, expect, it } from 'vitest';
import { byteCapacity, encodeQr, formatBits, qrPath, qrSvg, rsRemainder } from './qr';

// Mos yozuvlar Python `qrcode` kutubxonasi bilan yaratilgan (bayt rejimi, M daraja,
// qat'iy maska, border=0). Har qator — modullar ikkilik son sifatida (hex).
const VECTORS: Array<{ text: string; mask: number; version: number; rows: string[] }> = [{"text": "HELLO", "mask": 0, "version": 1, "rows": ["1fce7f", "105641", "17445d", "17465d", "17555d", "104d41", "1fd57f", "b00", "154a12", "150c42", "cd1f", "15ac42", "ced54", "16a6", "1fc2e7", "1047b0", "1756e7", "174866", "175515", "104c52", "1fd567"]}, {"text": "https://example.uz", "mask": 3, "version": 2, "rows": ["1fdcd7f", "1054d41", "174485d", "175535d", "1749f5d", "1044541", "1fd557f", "1cf00", "16e5f4b", "9320a2", "8df5f0", "1d2cc0c", "1ff82d7", "c96bf1", "d59516", "1691bf1", "1663ff", "19915", "1fd3157", "1055313", "17439f8", "1759edf", "175b8d6", "10402d4", "1fdd4ff"]}, {"text": "http://localhost:15173/royxatdan-otish?guruh=DI-2301", "mask": 5, "version": 4, "rows": ["1fc14147f", "1057c9541", "1759bfd5d", "17590125d", "17492435d", "10465dd41", "1fd55557f", "1e00500", "105ffd7ce", "1d036723c", "56b35dd6", "1a34400fe", "12f5fe940", "235a24b", "160480ea", "e2ca104d", "16dbc95b9", "5357ae4d", "14e032e4f", "1a190d5fd", "14c4110bb", "1c87576bc", "1748bddd6", "1637463cc", "1e5a227f9", "1576d15", "1fc975f56", "104411317", "174d451f8", "17409ae93", "1748537b7", "10463229c", "1fd5193ba"]}, {"text": "https://davomat.fjsti.uz/royxatdan-otish?guruh=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "mask": 2, "version": 7, "rows": ["1fccd688e97f", "1045e6128241", "1751ec0eca5d", "175c1f84e35d", "175427fcef5d", "105a25120841", "1fd55555557f", "17af194100", "17cf85f0e97c", "160ced99e31f", "177f40264fe6", "b8027007dec", "10f44daae8c1", "143ce3985b84", "1cd1443246ee", "1285ceb2d92e", "e690e186084", "1bafb4586384", "2d534723a2e", "f09fe320a3e", "ff23ff861f4", "31d0510611d", "1950595a8b56", "5125115491c", "5f80bf8e3fa", "8032753e185", "ed81a7458e", "172c5f32b41f", "77de7392451", "9a998bba144", "1fbe9b16c2e", "88f40129a6e", "1977b03820a4", "1c8ca598f104", "15c01523b8e", "f2a0cfe8b6e", "137899f4e1f4", "11f11ce31f", "1fcf71524b56", "10544f1f431e", "175569f4eff8", "1758267be129", "175d1c9c4f82", "104479907384", "1fd846fae522"]}, {"text": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "mask": 6, "version": 10, "rows": ["1fd6e7177777e7f", "105f8451ac1a241", "1750a3cc0ac1e5d", "174b1ae75777a5d", "175f7c57f3e525d", "1049517c4ac1c41", "1fd55555555557f", "e568446b0400", "13f231e7cf94e97", "40224f1ddddfd2", "19f4c07706b07bf", "1728dd2bb06b264", "1bd07833ddddcd2", "1ba6a622f94fb40", "164a1b0fb06b164", "14b6146a222202d", "1574ea44f94f840", "1214be554f94d9b", "1650457e222232d", "1e028f0786b04bf", "18f630e50f94e9b", "1735f0b19dddfd2", "1779db37c6b07bf", "1389586a806b264", "1c4b7dc1cdddcd2", "161267f8e94fb40", "13fe045fd06b1f4", "f1a1044622211d", "b5fff85794fb50", "15175c9c4f94d1b", "1dfccd77e2221fd", "f8c424186b061f", "359a4780f94dcb", "8b505575dddd71", "12d42fda46b04ee", "41af9f4306b0c4", "147ed8f9dddf83", "41d363b794f9e0", "1fe6e61af06b234", "408bacaa22228d", "86c7e85b94fb10", "8a1e953cf94f3b", "13fba733622207d", "c212181b6b061f", "55ba5e86f94dcb", "1425a877ddddd72", "14de3a7ac6b04ef", "1f25baec706b0c4", "7a4ccfddddff2", "12be3c794f910", "1fd9a19d706b154", "1056c3c4622211d", "175e7ebff94f9f0", "175455ce8f94c68", "174318a9e2221df", "1042f1ecc6b054f", "1fdc54a28f94c68"]}, {"text": "Guruh: O‘zbek тест", "mask": 1, "version": 2, "rows": ["1fd7f7f", "1043b41", "175d75d", "174155d", "1746a5d", "1053241", "1fd557f", "f800", "1466725", "183a613", "37dae9", "636e0a", "145e9a1", "31c7bb", "1deae85", "48cd3b", "19e7ff9", "15114", "1fd9d5d", "104bf10", "1745bf2", "1744586", "175bf1b", "104ad40", "1fd7db9"]}];

function rowHex(row: boolean[]): string {
  return BigInt('0b' + row.map((v) => (v ? '1' : '0')).join('')).toString(16);
}

describe('qr', () => {
  it.each(VECTORS.map((v) => [v.text.slice(0, 24), v] as const))('mos yozuv bilan bir xil: %s', (_label, v) => {
    const qr = encodeQr(v.text, { mask: v.mask });
    expect(qr.version).toBe(v.version);
    expect(qr.size).toBe(v.version * 4 + 17);
    expect(qr.modules.map(rowHex)).toEqual(v.rows);
  });

  it('Reed–Solomon: standartdagi misol (1-M, "01234567")', () => {
    // ISO/IEC 18004 I-ilova: 1-M, raqamli "01234567" ma'lumot kodso'zlari va ECC
    const data = [0x10, 0x20, 0x0c, 0x56, 0x61, 0x80, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11, 0xec, 0x11];
    expect(rsRemainder(data, 10)).toEqual([0xa5, 0x24, 0xd4, 0xc1, 0xed, 0x36, 0xc7, 0x87, 0x2c, 0x55]);
  });

  it('format bitlari (M daraja) standart jadval bilan mos', () => {
    expect(formatBits(0).toString(2).padStart(15, '0')).toBe('101010000010010');
    expect(formatBits(5).toString(2).padStart(15, '0')).toBe('100000011001110');
    expect(formatBits(7).toString(2).padStart(15, '0')).toBe('100101010100000');
  });

  it("sig'im: 1-M 14 bayt, 10-M 213 bayt", () => {
    expect(byteCapacity(1)).toBe(14);
    expect(byteCapacity(10)).toBe(213);
    expect(encodeQr('a'.repeat(14)).version).toBe(1);
    expect(encodeQr('a'.repeat(15)).version).toBe(2);
    expect(() => encodeQr('a'.repeat(214))).toThrow(RangeError);
  });

  it('avto maska — 8 tadan biri, natija barqaror', () => {
    const a = encodeQr('https://example.uz/royxatdan-otish?guruh=DI-2301');
    const b = encodeQr('https://example.uz/royxatdan-otish?guruh=DI-2301');
    expect(a.mask).toBeGreaterThanOrEqual(0);
    expect(a.mask).toBeLessThan(8);
    expect(a.modules).toEqual(b.modules);
  });

  it('SVG: sokin hudud va path', () => {
    const qr = encodeQr('HELLO', { mask: 0 });
    expect(qrPath(qr.modules, 4).startsWith('M4 4h7')).toBe(true);
    const svg = qrSvg('HELLO', { mask: 0 });
    expect(svg).toContain('viewBox="0 0 29 29"');
  });
});
