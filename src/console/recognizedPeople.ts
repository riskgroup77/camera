import type { LiveDetectionResult } from '../types';

/** Tanlangan kamerada shu ko'rish davomida tanilgan odam (o'ng ustundagi karta). */
export interface SeenPerson {
  id: string;
  name: string;
  type: string | null;
  unit: string | null;
  photoUrl: string | null;
  similarity: number | null;
  firstSeen: number;
  lastSeen: number;
  /** Oxirgi skaner natijasida kadrda bor. */
  inFrame: boolean;
}

/** Ustunda shundan ko'p karta turmaydi — eng eskilari tushib qoladi. */
export const MAX_SEEN_PEOPLE = 12;

/** Yangi skaner natijasini ro'yxatga qo'shadi. Tartib: hozir kadrdagilar
 *  (avval yangi kelganlar), keyin oxirgi ko'ringan vaqti bo'yicha. Natija
 *  o'zgarmasa — o'sha massiv (React qayta chizmaydi). */
export function mergeSeenPeople(
  prev: SeenPerson[],
  scan: LiveDetectionResult | null,
  now: number,
  max = MAX_SEEN_PEOPLE,
): SeenPerson[] {
  if (!scan) return prev;
  const present = new Map<string, LiveDetectionResult['faces'][number]>();
  for (const face of scan.faces ?? []) {
    if (face.status === 'tanildi' && face.personId && face.personName) present.set(face.personId, face);
  }
  if (present.size === 0 && prev.every((person) => !person.inFrame)) return prev;

  const byId = new Map(prev.map((person) => [person.id, person]));
  const next: SeenPerson[] = prev.map((person) => (person.inFrame && !present.has(person.id) ? { ...person, inFrame: false } : person));
  for (const [id, face] of present) {
    const old = byId.get(id);
    const updated: SeenPerson = {
      id,
      name: face.personName ?? old?.name ?? '',
      type: face.personType ?? old?.type ?? null,
      unit: face.personUnit ?? old?.unit ?? null,
      photoUrl: face.photoUrl ?? old?.photoUrl ?? null,
      similarity: face.similarity ?? old?.similarity ?? null,
      firstSeen: old && old.inFrame ? old.firstSeen : now,
      lastSeen: now,
      inFrame: true,
    };
    const index = next.findIndex((person) => person.id === id);
    if (index >= 0) next[index] = updated;
    else next.push(updated);
  }
  next.sort((a, b) => Number(b.inFrame) - Number(a.inFrame) || (a.inFrame ? b.firstSeen - a.firstSeen : b.lastSeen - a.lastSeen));
  return next.slice(0, max);
}
