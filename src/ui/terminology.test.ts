import { describe, expect, it } from 'vitest';
import { ATTENDANCE_STATUS } from './status';

/**
 * Yagona atama qo'riqchisi.
 *
 * Bitta holat uchun oltita yorliq ishlatilardi ("Kech", "Kech qoldi",
 * "Kechikdi", "Kechikkan"...) — bir sahifada ikkitasi yonma-yon chiqardi.
 * Kanonik ro'yxat src/ui/status.ts'da; bu sinov eski variantlar qaytib
 * kelmasligini tekshiradi.
 */

// Uslub qo'llanmasi atamalarni namoyish qiladi — tekshiruvdan chetda.
const sources = import.meta.glob('../**/*.{ts,tsx}', { eager: true, query: '?raw', import: 'default' }) as Record<string, string>;

/** Taqiqlangan variant → o'rniga ishlatiladigan kanonik yorliq. */
const BANNED: RegExp[] = [/Kech qold/, /Kech qolgan/, /Kechikdi/, /Kechikkan(?! \/)/];

/**
 * Rahbar tushunmaydigan atamalar.
 *
 * Buyurtmachi "juda ham tushunarli emas" degani shu so'zlar haqida edi:
 * ekranda "kesim", "punktuallik", "diagnostika" turganda direktor raqamning
 * nimani anglatishini tusholmaydi. Har biri uchun sodda muqobil bor.
 */
const JARGON: Array<{ pattern: RegExp; instead: string }> = [
  { pattern: /\bkesimida\b/i, instead: "«bo'yicha» yoki «har bir ... da»" },
  { pattern: /punktuallik/i, instead: "«darsga o'z vaqtida kirish»" },
  { pattern: /\bmedian\b/i, instead: "«o'rtacha»" },
  { pattern: /diagnostikasi/i, instead: '«... ishlayaptimi»' },
  // Faqat bosh harfli shakl — kichik harfli "surunkali" manzil/tab kaliti
  // sifatida koddan ishlatiladi va foydalanuvchiga ko'rinmaydi.
  { pattern: /\bSurunkali\b/, instead: '«Takror kechikkan»' },
  { pattern: /\bonlayn\b/i, instead: '«aloqada» yoki «ishlab turgan»' },
  { pattern: /\bSLA\b/, instead: "«muddat»" },
  { pattern: /\bROI\b/, instead: "«hudud»" },
  { pattern: /Ruxsat \/ FPS/, instead: '«Tasvir sifati»' },
];

const SKIP = /StyleGuidePage\.tsx$|terminology\.test\.ts$/;

/** Jargon qo'riqchisi faqat qayta yozilgan ekranlarni qamrab oladi.
 *  Qolgan bo'limlar navbat bilan tozalanadi — ro'yxat shunda kengayadi. */
const JARGON_SCOPE =
  /(pages\/situation|pages\/students|pages\/teachers|pages\/person|pages\/wall|components\/situation|components\/students|components\/teachers|components\/attendance|components\/videowall|components\/wall|layouts)\//;

describe('atamalar', () => {
  it('kanonik yorliqlar kutilganidek', () => {
    expect(ATTENDANCE_STATUS.keldi.label).toBe('Keldi');
    expect(ATTENDANCE_STATUS.kech_keldi.label).toBe('Kech keldi');
    expect(ATTENDANCE_STATUS.kelmadi.label).toBe('Kelmadi');
    expect(ATTENDANCE_STATUS.nomalum.label).toBe("Ma'lumot yo'q");
  });

  it('"kech keldi" uchun eski variantlar ishlatilmaydi', () => {
    const canonical = ATTENDANCE_STATUS.kech_keldi.label;
    // Glob ishlayotganiga ishonch: aks holda sinov jimgina "o'tib" ketardi.
    expect(Object.keys(sources).length).toBeGreaterThan(200);
    const problems: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (SKIP.test(file)) continue;
      source.split('\n').forEach((line, index) => {
        // Faqat foydalanuvchiga ko'rinadigan matn: izohlar hisobga olinmaydi.
        const code = line.replace(/\/\/.*$/, '').replace(/^\s*\*.*$/, '');
        if (BANNED.some((pattern) => pattern.test(code))) {
          problems.push(`${file}:${index + 1} — "${canonical}" ishlatilsin: ${code.trim()}`);
        }
      });
    }
    expect(problems).toEqual([]);
  });

  it('asosiy ekranlarda rahbar tushunmaydigan atamalar yo\'q', () => {
    const problems: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (SKIP.test(file) || !JARGON_SCOPE.test(file) || /\.test\.tsx?$/.test(file)) continue;
      source.split('\n').forEach((line, index) => {
        // Izohlar dasturchi uchun — faqat foydalanuvchiga ko'rinadigan matn.
        const code = line
          .replace(/\/\*.*?\*\//g, '')
          .replace(/\/\/.*$/, '')
          .replace(/^\s*(\/\*|\*).*$/, '');
        for (const { pattern, instead } of JARGON) {
          if (pattern.test(code)) problems.push(`${file}:${index + 1} — ${instead} ishlatilsin: ${code.trim()}`);
        }
      });
    }
    expect(problems).toEqual([]);
  });
});
