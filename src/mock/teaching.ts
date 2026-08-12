import type { LessonSession } from '../types';

const GROUPS = ['302-guruh', '204-guruh', '403-guruh', '101-guruh', '506-guruh'];
const FACULTIES = ['Davolash ishi', 'Farmatsiya', 'Pediatriya', 'Jamoat salomatligi'];
const TEACHERS = [
  'Prof. Toshmatov S.',
  'Prof. Karimov B.',
  'Dots. Nazarov K.',
  'Prof. Abdullayev R.',
  'Dots. Hasanov J.',
];
const SUBJECTS = ['Anatomiya', 'Fiziologiya', 'Farmakologiya', 'Ichki kasalliklar', 'Mikrobiologiya'];

function seededPick<T>(arr: T[], seed: number): T {
  return arr[seed % arr.length];
}

export const lessonSessions: LessonSession[] = Array.from({ length: 24 }, (_, i) => {
  const n = i + 1;
  const dayOffset = 13 - Math.floor(i / 2);
  const date = new Date(2026, 6, 30 - dayOffset).toISOString().slice(0, 10);

  const attentionScore = 55 + ((n * 13) % 40);
  const teacherActivityScore = 50 + ((n * 17) % 45);
  const sleepIncidents = (n * 3) % 5;

  return {
    id: `ls-${String(n).padStart(3, '0')}`,
    date,
    group: seededPick(GROUPS, n),
    faculty: seededPick(FACULTIES, n),
    teacher: seededPick(TEACHERS, n + 1),
    subject: seededPick(SUBJECTS, n),
    attentionScore,
    sleepIncidents,
    teacherActivityScore,
    teacherOnTime: n % 6 !== 0,
  };
});
