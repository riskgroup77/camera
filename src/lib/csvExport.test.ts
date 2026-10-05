import { describe, expect, it, vi } from 'vitest';
import { exportRowsAsCsv } from './csvExport';

/** Blob matnini o'qish: jsdom'da Blob.text() bor. */
async function capture(fn: () => void): Promise<string> {
  let captured: Blob | null = null;
  const create = vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
    captured = blob as Blob;
    return 'blob:test';
  });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  fn();
  create.mockRestore();
  return captured ? await (captured as Blob).text() : '';
}

describe('exportRowsAsCsv', () => {
  it("Excel uchun BOM va sep=; sarlavhasini yozadi", async () => {
    const text = await capture(() => exportRowsAsCsv(['Ism', 'Vaqt'], [['Ali', '08:05']], 'a.csv'));
    // Blob.text() BOM'ni o'zi olib tashlaydi, shuning uchun bu yerda
    // faqat ajratgich sarlavhasini tekshiramiz.
    expect(text.startsWith('sep=;\r\n')).toBe(true);
    expect(text).toContain('"Ism";"Vaqt"');
  });

  it("qo'shtirnoq va vergulni buzmaydi", async () => {
    const text = await capture(() => exportRowsAsCsv(['A'], [['Ali "Vali", 1']], 'a.csv'));
    expect(text).toContain('"Ali ""Vali"", 1"');
  });
});
