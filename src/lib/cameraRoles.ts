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
  kirish: 'Kunlik davomat, erta ketish, begona shaxs, oq xalat, chekish',
  auditoriya: 'Dars davomati, darsga kechikish, diqqat, o‘qituvchi faolligi, oq xalat',
  laboratoriya: 'Oq xalat, chekish',
  koridor: 'Oq xalat, chekish',
  ofis: 'Oq xalat, chekish',
  cheklangan: 'Begona shaxs, oq xalat, chekish',
  tashqi: 'Begona shaxs, chekish',
};

export const ROOM_TYPE_OPTIONS = (Object.keys(ROOM_TYPE_LABELS) as RoomType[]).map((value) => ({
  value,
  label: ROOM_TYPE_LABELS[value],
}));
