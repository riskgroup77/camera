/** Global qidiruv (buyruqlar palitrasi) uchun sof funksiyalar: matnni
 *  normallashtirish, moslik bahosi, ajratib ko'rsatish va so'nggi tanlovlar. */

const APOSTROPHES = /[‘’ʻʼ`´]/g;

/** Apostrof turlari (o‘, oʻ, o', o`) bitta; harflar kichik; diakritika olib tashlangan. */
export function normalize(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(APOSTROPHES, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

export interface MatchRange {
  start: number;
  end: number;
}

export interface MatchResult {
  /** Katta — yaxshiroq. */
  score: number;
  /** Asl matndagi mos kelgan bo'laklar (end — kirmaydi). */
  ranges: MatchRange[];
}

/** Belgima-belgi normallashtirish: indekslar asl matn bilan bir xil qoladi. */
function foldChars(text: string): string {
  let out = '';
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (/[‘’ʻʼ`´]/.test(ch)) out += "'";
    else if (/\s/.test(ch)) out += ' ';
    else {
      const base = ch.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
      out += base.length === 1 ? base : ch.toLowerCase().length === 1 ? ch.toLowerCase() : ch;
    }
  }
  return out;
}

function isWordStart(text: string, index: number): boolean {
  if (index === 0) return true;
  return /[\s\-_/.,(«"'·]/.test(text[index - 1]);
}

/** `query`ning `text`ga mosligi. So'zlar (bo'shliq bilan) har biri alohida
 *  topilishi kerak. Baho: to'liq moslik > boshidan > so'z boshidan > ichida >
 *  harflar ketma-ketligi (fuzzy). Mos kelmasa null. */
export function matchText(query: string, text: string): MatchResult | null {
  const q = normalize(query);
  if (!q) return { score: 0, ranges: [] };
  const hay = foldChars(text);

  if (normalize(text) === q) {
    const at = Math.max(0, hay.indexOf(q));
    return { score: 1000, ranges: [{ start: at, end: at + q.length }] };
  }

  const tokens = q.split(' ').filter(Boolean);
  const ranges: MatchRange[] = [];
  let score = 0;
  let allSubstring = true;

  for (const token of tokens) {
    let best = -1;
    let bestScore = -1;
    let from = 0;
    while (from <= hay.length) {
      const idx = hay.indexOf(token, from);
      if (idx < 0) break;
      const s = idx === 0 ? 300 : isWordStart(hay, idx) ? 200 : 100;
      if (s > bestScore) {
        bestScore = s;
        best = idx;
      }
      if (s === 300) break;
      from = idx + 1;
    }
    if (best < 0) {
      allSubstring = false;
      break;
    }
    ranges.push({ start: best, end: best + token.length });
    score += bestScore;
  }

  if (allSubstring) {
    // Qisqa matn (nomga yaqinroq) biroz oldinda.
    return { score: score / tokens.length + Math.max(0, 40 - hay.length) / 4, ranges: mergeRanges(ranges) };
  }

  // Fuzzy: so'rov harflari tartib bilan (bo'shliqsiz).
  const compact = q.replace(/ /g, '');
  if (compact.length < 3) return null;
  const fuzzy: MatchRange[] = [];
  let pos = 0;
  let gaps = 0;
  for (const ch of compact) {
    const idx = hay.indexOf(ch, pos);
    if (idx < 0) return null;
    if (idx > pos && fuzzy.length) gaps += 1;
    fuzzy.push({ start: idx, end: idx + 1 });
    pos = idx + 1;
  }
  return { score: Math.max(1, 60 - gaps * 8 - (hay.length - compact.length) / 10), ranges: mergeRanges(fuzzy) };
}

export function mergeRanges(ranges: readonly MatchRange[]): MatchRange[] {
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const out: MatchRange[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r.start <= last.end) last.end = Math.max(last.end, r.end);
    else out.push({ ...r });
  }
  return out;
}

export interface HighlightPart {
  text: string;
  match: boolean;
}

/** Matnni mos kelgan / kelmagan bo'laklarga ajratadi (<mark> uchun). */
export function highlight(text: string, ranges: readonly MatchRange[]): HighlightPart[] {
  if (!ranges.length) return text ? [{ text, match: false }] : [];
  const parts: HighlightPart[] = [];
  let pos = 0;
  for (const r of mergeRanges(ranges)) {
    const start = Math.max(pos, Math.min(r.start, text.length));
    const end = Math.min(r.end, text.length);
    if (start > pos) parts.push({ text: text.slice(pos, start), match: false });
    if (end > start) parts.push({ text: text.slice(start, end), match: true });
    pos = Math.max(pos, end);
  }
  if (pos < text.length) parts.push({ text: text.slice(pos), match: false });
  return parts;
}

export interface Searchable {
  id: string;
  title: string;
  /** Qo'shimcha qidiriladigan matnlar (kalit so'zlar, izoh). Nomdan pastroq baholanadi. */
  keywords?: string[];
}

export interface Ranked<T> {
  item: T;
  score: number;
  /** `title` ichidagi moslik (ajratib ko'rsatish uchun). */
  ranges: MatchRange[];
}

/** Elementlarni so'rov bo'yicha baholab, eng mosini birinchi qo'yadi.
 *  Bo'sh so'rov — asl tartib. */
export function rankItems<T extends Searchable>(query: string, items: readonly T[], limit = Infinity): Ranked<T>[] {
  const q = normalize(query);
  if (!q) return items.slice(0, limit).map((item) => ({ item, score: 0, ranges: [] }));
  const out: Array<{ r: Ranked<T>; index: number }> = [];
  items.forEach((item, index) => {
    const onTitle = matchText(q, item.title);
    let best: { score: number; ranges: MatchRange[] } | null = onTitle;
    for (const kw of item.keywords ?? []) {
      const m = matchText(q, kw);
      const kwScore = m ? Math.min(m.score, 300) * 0.6 : 0;
      if (m && (!best || kwScore > best.score)) best = { score: kwScore, ranges: onTitle?.ranges ?? [] };
    }
    if (best) out.push({ r: { item, score: best.score, ranges: best.ranges }, index });
  });
  return out
    .sort((a, b) => b.r.score - a.r.score || a.index - b.index)
    .slice(0, limit)
    .map(({ r }) => r);
}

// ───────────────────────────────────────────── So'nggi tanlovlar

export interface RecentItem {
  kind: string;
  id: string;
  title: string;
  subtitle?: string;
  to: string;
}

export const RECENT_KEY = 'command-palette-recent';
export const RECENT_LIMIT = 8;

type ReadStore = Pick<Storage, 'getItem'>;
type RWStore = Pick<Storage, 'getItem' | 'setItem'>;

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadRecent(storage: ReadStore | null = safeStorage()): RecentItem[] {
  try {
    const raw = storage?.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (r): r is RecentItem =>
          Boolean(r) && typeof r === 'object' && typeof r.to === 'string' && typeof r.title === 'string' && typeof r.kind === 'string' && typeof r.id === 'string',
      )
      .slice(0, RECENT_LIMIT);
  } catch {
    return [];
  }
}

/**
 * So'nggi tanlovlardan FOYDALANUVCHI HOZIR OCHA OLADIGANLARINI qoldiradi.
 *
 * Ro'yxat brauzerda saqlanadi va rol/huquq o'zgarganini bilmaydi. Shu
 * bilan bir kompyuterda ishlagan (yoki roli pasaytirilgan) odam Ctrl+K
 * bosishi bilan "Hodisalar", "Talabalar" yoki boshqa birovning
 * shaxs sahifasini ko'rardi — va bosganda bo'sh/"huquq yo'q" ekranga
 * tushardi. Endi ochib bo'lmaydigan yozuv umuman ko'rinmaydi.
 *
 * `allowedPages` — menyuda hozir ko'rinayotgan manzillar; `allowKind` —
 * tur bo'yicha huquq (shaxs, guruh, kamera…); `allowPath` — roldan
 * kelib chiqqan qo'shimcha cheklov (kamera mas'uli — ikki sahifa).
 */
export function visibleRecent(
  items: readonly RecentItem[],
  {
    allowedPages,
    allowKind,
    allowPath,
  }: {
    allowedPages: ReadonlySet<string>;
    allowKind: (kind: string) => boolean;
    allowPath?: (to: string) => boolean;
  },
): RecentItem[] {
  return items.filter((item) => {
    const path = item.to.split('?')[0];
    if (allowPath && !allowPath(path)) return false;
    if (item.kind === 'page') return allowedPages.has(path);
    return allowKind(item.kind);
  });
}

/** Yangi tanlovni boshiga qo'shadi (takrorlarsiz), yangi ro'yxatni qaytaradi. */
export function pushRecent(item: RecentItem, storage: RWStore | null = safeStorage()): RecentItem[] {
  const next = [item, ...loadRecent(storage).filter((r) => !(r.kind === item.kind && r.id === item.id))].slice(0, RECENT_LIMIT);
  try {
    storage?.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* saqlab bo'lmadi — xotirada baribir ishlaydi */
  }
  return next;
}
