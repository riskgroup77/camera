/* ------------------------------------------------------------------
 * BLANK RAQAMI — to'ldiriladigan formalar uchun.
 *
 * Hisobotlarda hujjat raqami bor (`lib/hisobotApi.ts` → `buildReference`),
 * formalarda esa blank raqami: rasmiy blankning yuqori o'ng burchagidagi
 * yozuv. Odam qo'ng'iroq qilganda ("qaysi formada to'xtab qoldingiz?")
 * yoki ekrandan surat yuborganda aynan shu raqam gapiradi.
 *
 * Shakl: TASHKILOT / FORMA / BOSQICH / TARTIB
 *   FERMI/KIR/0001
 *   FERMI/RYX/B2-4/0338
 *
 * Raqam FORMA HOLATIDAN kelib chiqadi va TASODIFIY EMAS: bir xil
 * holat — doim bir xil raqam. Shuning uchun bu yerda `Date`, `Math.random`
 * yoki render hisoblagichi ishlatilmaydi; tartib raqami tanlovning
 * o'zidan (FNV-1a) hisoblanadi. Aks holda har bosishda raqam o'zgarib,
 * blank raqamining ma'nosi qolmasdi.
 * ------------------------------------------------------------------ */

/** Tashkilot kodi — boshqa muassasaga o'rnatishda almashtiriladi. */
export const FORM_ORG_CODE = 'FERMI';

/** Formalar: kirish, parolni tiklash, ochiq ro'yxatdan o'tish. */
export type FormKind = 'kirish' | 'parol' | 'royxat';

const FORM_CODE: Record<FormKind, string> = {
  kirish: 'KIR',
  parol: 'PRL',
  royxat: 'RYX',
};

/**
 * Tanlovdan deterministik 4 xonali tartib raqami (0002–9999).
 * Bo'laklar bo'sh bo'lsa — 0001 (formaning asosiy, to'ldirilmagan holati).
 */
export function formSerial(parts: readonly (string | null | undefined)[]): string {
  const key = parts
    .map((part) => (part ?? '').trim())
    .filter(Boolean)
    .join('|');
  if (!key) return '0001';
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return String((hash % 9998) + 2).padStart(4, '0');
}

/**
 * Blank raqamini tuzadi.
 *
 * `step`/`of` berilsa bosqich bo'lagi qo'shiladi: "B2-4" — to'rt
 * bosqichli formaning ikkinchisi. `parts` — raqamga ta'sir qiladigan
 * holat bo'laklari (forma turi, tanlangan usul, guruh kodi va h.k.).
 * MAXFIY qiymat (parol, JSHSHIR, pasport raqami) bu yerga UZATILMAYDI:
 * blank raqami ekranda turadi va suratga tushadi.
 */
export function formNumber(input: {
  kind: FormKind;
  /** Bosqich tartibi (1 dan boshlanadi). */
  step?: number;
  /** Jami bosqichlar. */
  of?: number;
  parts?: readonly (string | null | undefined)[];
  org?: string;
}): string {
  const org = (input.org ?? FORM_ORG_CODE).toUpperCase();
  const serial = formSerial(input.parts ?? []);
  const stage =
    input.step && input.of && input.step >= 1 && input.step <= input.of
      ? `B${input.step}-${input.of}/`
      : '';
  return `${org}/${FORM_CODE[input.kind]}/${stage}${serial}`;
}
