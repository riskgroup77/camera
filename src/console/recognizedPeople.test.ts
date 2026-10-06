import { describe, expect, it } from 'vitest';
import { mergeSeenPeople } from './recognizedPeople';
import type { DetectedFace, LiveDetectionResult } from '../types';

const face = (id: string, extra: Partial<DetectedFace> = {}): DetectedFace => ({
  bbox: [0, 0, 10, 10],
  asleep: false,
  status: 'tanildi',
  personId: id,
  personName: `Odam ${id}`,
  personUnit: '101-guruh',
  photoUrl: `https://s3/${id}.jpg`,
  similarity: 0.71,
  ...extra,
});
const scan = (...faces: DetectedFace[]): LiveDetectionResult => ({ frameWidth: 2560, frameHeight: 1440, faces });

describe('mergeSeenPeople', () => {
  it("tanilganlarni qo'shadi, notanish va kichik yuzlarni o'tkazib yuboradi", () => {
    const people = mergeSeenPeople(
      [],
      scan(face('a'), face('x', { status: 'notanish', personId: null, personName: null }), face('k', { status: 'kichik' })),
      1000,
    );
    expect(people.map((p) => [p.id, p.name, p.inFrame, p.photoUrl])).toEqual([['a', 'Odam a', true, 'https://s3/a.jpg']]);
  });

  it("kadrdan chiqqan odam qoladi, lekin kadrdagilardan keyin", () => {
    let people = mergeSeenPeople([], scan(face('a')), 1000);
    people = mergeSeenPeople(people, scan(face('a'), face('b')), 2000);
    people = mergeSeenPeople(people, scan(face('b')), 3000);
    expect(people.map((p) => [p.id, p.inFrame, p.lastSeen])).toEqual([
      ['b', true, 3000],
      ['a', false, 2000],
    ]);
  });

  it('kadrdagilar orasida yangi kelgan yuqorida', () => {
    let people = mergeSeenPeople([], scan(face('a')), 1000);
    people = mergeSeenPeople(people, scan(face('a'), face('b')), 2000);
    expect(people.map((p) => p.id)).toEqual(['b', 'a']);
  });

  it("o'zgarish bo'lmasa o'sha massiv qaytadi (qayta chizilmaydi)", () => {
    const people = mergeSeenPeople([], scan(face('a')), 1000);
    const left = mergeSeenPeople(people, scan(), 2000);
    expect(mergeSeenPeople(left, scan(), 3000)).toBe(left);
    expect(mergeSeenPeople(left, null, 3000)).toBe(left);
  });

  it("ro'yxat chegaralangan — eng eskisi tushadi", () => {
    let people = mergeSeenPeople([], scan(face('a')), 1000);
    people = mergeSeenPeople(people, scan(face('b')), 2000);
    people = mergeSeenPeople(people, scan(face('c')), 3000, 2);
    expect(people.map((p) => p.id)).toEqual(['c', 'b']);
  });
});
