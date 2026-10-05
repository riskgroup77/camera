/**
 * Svetofor qoidasi — butun tizim bo'ylab YAGONA.
 *
 * Rahbar ekranda raqamni emas, RANGNI ko'radi: yashil — talab
 * bajarilgan, sariq — chegarada, qizil — chora ko'rish kerak.
 * Rang hech qachon yolg'iz qolmaydi: har joyda harf (Y/S/Q) yoki
 * so'z bilan birga chiqadi — ranglarni ajratmaydigan odam ham,
 * oq-qora bosma ham to'g'ri o'qiydi.
 */

export type Rag = 'yashil' | 'sariq' | 'qizil' | 'yoq';

export interface RagThresholds {
  /** Shu qiymatdan boshlab yashil. */
  ok: number;
  /** Shu qiymatdan boshlab sariq; undan past — qizil. */
  warn: number;
}

/** Davomat foizi uchun standart chegaralar. */
export const RATE_RAG: RagThresholds = { ok: 90, warn: 75 };

/** Kechikish ULUSHI uchun — bu yerda KAM bo'lgani yaxshi. */
export const LATE_RAG: RagThresholds = { ok: 5, warn: 15 };

/** Qiymat -> svetofor. `null`/`NaN` — "yoq" (o'lchanmagan). */
export function rag(value: number | null | undefined, t: RagThresholds = RATE_RAG): Rag {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'yoq';
  // Chegaralar teskari bo'lsa (kam bo'lgani yaxshi ko'rsatkich) qiyoslash
  // ham teskari ishlaydi — chaqiruvchi alohida bayroq uzatmasin.
  const inverted = t.ok < t.warn;
  if (inverted) {
    if (value <= t.ok) return 'yashil';
    if (value <= t.warn) return 'sariq';
    return 'qizil';
  }
  if (value >= t.ok) return 'yashil';
  if (value >= t.warn) return 'sariq';
  return 'qizil';
}

/** Ranglarni ajratmaydigan o'quvchi uchun qisqa harf. */
export const RAG_LETTER: Record<Rag, string> = {
  yashil: 'Y',
  sariq: 'S',
  qizil: 'Q',
  yoq: '—',
};

export const RAG_LABEL: Record<Rag, string> = {
  yashil: 'Me’yorda',
  sariq: 'Chegarada',
  qizil: 'Chora kerak',
  yoq: "O'lchanmagan",
};

/** Matn rangi. */
export const RAG_TEXT: Record<Rag, string> = {
  yashil: 'text-success',
  sariq: 'text-warning',
  qizil: 'text-danger',
  yoq: 'text-subtle',
};

/** Yumshoq fon + chegara (katak va yorliqlar uchun). */
export const RAG_FILL: Record<Rag, string> = {
  yashil: 'bg-success-soft text-success',
  sariq: 'bg-warning-soft text-warning',
  qizil: 'bg-danger-soft text-danger',
  yoq: 'bg-surface-2 text-subtle',
};

/** To'q rang — chiroq va ustun uchun. */
export const RAG_SOLID: Record<Rag, string> = {
  yashil: 'bg-success',
  sariq: 'bg-warning',
  qizil: 'bg-danger',
  yoq: 'bg-subtle',
};

/** Chegaralarni odamcha tushuntirish — izohlar va yordam matni uchun. */
export function ragHint(t: RagThresholds = RATE_RAG, unit = '%'): string {
  const inverted = t.ok < t.warn;
  return inverted
    ? `Yashil: ${t.ok}${unit} gacha · Sariq: ${t.warn}${unit} gacha · Qizil: ${t.warn}${unit} dan yuqori`
    : `Yashil: ${t.ok}${unit} va yuqori · Sariq: ${t.warn}${unit} dan · Qizil: ${t.warn}${unit} dan past`;
}
