/** Eski /admin/* manzillari → yangi manzillar. Xatcho'plar, elektron
 *  xatlardagi (parolni tiklash) va Telegram bildirishnomalaridagi havolalar
 *  ishlashda davom etishi uchun. Query (`?id=`, `?search=`, `?token=`)
 *  va hash saqlanadi. */
const LEGACY_MAP: Record<string, string> = {
  '/admin': '/',
  '/admin/events': '/hodisalar',
  '/admin/students-staff': '/reestr',
  '/admin/attendance': '/talabalar',
  '/admin/presence': '/oqituvchilar',
  // Darslar sahifasi olib tashlangan (2026-09-19) — situatsion markazga.
  '/admin/teaching': '/',
  '/admin/org-structure': '/tuzilma',
  '/admin/cameras': '/sozlamalar/kameralar',
  '/admin/ai-modules': '/sozlamalar/ai',
  '/admin/reports': '/hisobotlar',
  '/admin/users-roles': '/sozlamalar/foydalanuvchilar',
  '/admin/system-log': '/sozlamalar/tizim?tab=jurnal',
  '/admin/video-wall': '/videodevor',
  // Qavat rejalari endi xaritada.
  '/admin/floor-plans': '/xarita',
  '/admin/notifications': '/sozlamalar/bildirishnomalar',
  '/admin/integrations': '/sozlamalar/integratsiyalar',
  '/admin/privacy': '/sozlamalar/maxfiylik',
  '/admin/login': '/kirish',
  '/admin/reset-password': '/parolni-tiklash',
};

/** Eski "Bino va qavat bo'yicha" ekrani (/videodevor?tab=binolar) endi
 *  videodevorning yon panelidagi daraxt. Eski havolalar tushib qolmasin:
 *  - `?q=` — yon paneldagi qidiruvga tushadi;
 *  - `?kamera=<id>` — o'sha kamera devorga qo'yiladi;
 *  - `?bino=`/`?qavat=` — bino identifikatori (UUID) edi, nomi esa faqat
 *    kampus so'rovidan bilinardi: ular tashlab yuboriladi, operator yon
 *    paneldan binoni bir bosishda topadi;
 *  - `?tab=` — endi tab yo'q. */
const CAMPUS_PARAMS = ['bino', 'qavat', 'kamera', 'q', 'tab'] as const;

export interface VideoWallEntry {
  /** Yon panelning boshlang'ich qidiruvi. */
  search: string;
  /** Devorga qo'yiladigan kamera (eski `?kamera=`). */
  cameraId: string | null;
  /** Eski parametrlardan tozalangan query (`?` belgisisiz). */
  nextSearch: string;
  /** URL'ni almashtirish kerakmi. */
  changed: boolean;
}

/** /videodevor manziliga eski parametrlar bilan kelingan bo'lsa — nimani
 *  saqlab qolish va URL'ni nimaga almashtirish kerakligini aytadi. */
export function videoWallEntry(search: string): VideoWallEntry {
  const params = new URLSearchParams(search);
  const next = new URLSearchParams(search);
  let changed = false;
  for (const key of CAMPUS_PARAMS) {
    if (next.has(key)) {
      next.delete(key);
      changed = true;
    }
  }
  return {
    search: (params.get('q') ?? '').trim(),
    cameraId: params.get('kamera') || null,
    nextSearch: next.toString(),
    changed,
  };
}

/** Eski manzil uchun yangi to'liq manzil (noma'lum /admin/... → "/"). */
export function legacyRedirect(pathname: string, search = '', hash = ''): string {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  // Eski davomat kalendari aniq bir odamni ?person=<id> bilan ochardi —
  // endi bu shaxs profili.
  if (clean === '/admin/attendance') {
    const person = new URLSearchParams(search).get('person');
    if (person) return `/shaxs/${encodeURIComponent(person)}${hash}`;
  }
  const target = LEGACY_MAP[clean] ?? '/';
  const [targetPath, targetQuery = ''] = target.split('?');
  // Eski query saqlanadi; yangi manzilning o'z parametri (tab=jurnal) ustun.
  const params = new URLSearchParams(search);
  new URLSearchParams(targetQuery).forEach((value, key) => {
    params.set(key, value);
  });
  const query = params.toString();
  return `${targetPath}${query ? `?${query}` : ''}${hash}`;
}
