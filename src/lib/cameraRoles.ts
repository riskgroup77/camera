import type { RoomType } from '../types';

/** Backend app/services/camera_roles.py ROOM_TYPE_LABELS bilan bir xil. */
export const ROOM_TYPE_LABELS: Record<RoomType, string> = {
  kirish: 'Kirish/chiqish',
  auditoriya: 'Auditoriya (dars xonasi)',
  laboratoriya: 'Laboratoriya/klinika',
  koridor: 'Koridor/zina',
  ofis: 'Ofis/kafedra',
  cheklangan: 'Cheklangan xona',
  tashqi: 'Tashqi hudud (perimetr)',
};

/** Qaysi modullar shu turda ishlashi — admin tanlayotganda ko'rsatiladi. */
export const ROOM_TYPE_HINTS: Record<RoomType, string> = {
  kirish: 'Kunlik davomat, kechki kirish, begona shaxs',
  auditoriya: 'Dars jadvali bo‘yicha tekshiruvlar, uyqu',
  laboratoriya: 'Faqat xavfsizlik mezonlari',
  koridor: 'Faqat xavfsizlik mezonlari',
  ofis: 'Faqat xavfsizlik mezonlari',
  cheklangan: 'Begona shaxs, taqiqlangan zona',
  tashqi: 'Begona shaxs',
};

export const ROOM_TYPE_OPTIONS = (Object.keys(ROOM_TYPE_LABELS) as RoomType[]).map((value) => ({
  value,
  label: ROOM_TYPE_LABELS[value],
}));
