import type { CriterionCell, CriterionTone, GroupCriteria, GroupCriteriaPerson, GroupCriterion } from './groupCriteriaApi';

/**
 * Nazorat → guruh → "Kriteriyalar" → "Namuna": taqdimot uchun to'qima
 * ma'lumot. Ismlar ham to'qima ("Namuna talaba 01") — soxta "chekdi",
 * "diqqati past" belgilari hech qachon haqiqiy talaba ismi yoniga
 * tushmaydi. Faqat brauzerda hosil qilinadi: bazaga yozilmaydi, hisobotga
 * tushmaydi. Bir guruh va kun uchun har safar bir xil (urug'li tasodif).
 */

export const SAMPLE_LABEL = 'NAMUNA — taqdimot uchun to‘qima ma’lumot, haqiqiy emas';

/** mulberry32 — kichik, urug'li tasodifiy sonlar generatori. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

const cell = (value: string, tone: CriterionTone, title: string, evidence = 0): CriterionCell => ({
  value,
  tone,
  title,
  evidence: evidence || null,
});

const pct = (part: number, whole: number) => (whole ? Math.round((100 * part) / whole) : 0);

function criterion(key: string, code: number, label: string, indicator: string, tone: CriterionTone): GroupCriterion {
  return { key, code, label, description: `${label} (namuna)`, indicator, tone, unavailable: null, note: null };
}

export interface SampleTeacher {
  /** O'qituvchi faolligi (21) — darsdagi harakat balli. */
  activity: number;
  /** O'qituvchining darsga kelishi (22). */
  arrival: string;
  arrivalTone: CriterionTone;
}

export function sampleGroupCriteria(group: string, date: string, size: number): GroupCriteria & { teacher: SampleTeacher } {
  const random = rng(hash(`${group}|${date}`));
  const count = Math.max(6, Math.min(size || 20, 40));
  const smokers = new Set<number>();
  const smokerCount = 1 + Math.floor(random() * 2); // 1-2 kishi
  while (smokers.size < smokerCount) smokers.add(Math.floor(random() * count));

  const people: GroupCriteriaPerson[] = [];
  let came = 0;
  let late = 0;
  let lessonsAttended = 0;
  let lessonsTotal = 0;
  let lessonLate = 0;
  let leftEarly = 0;
  let noCoat = 0;
  let lowAttention = 0;
  for (let i = 0; i < count; i += 1) {
    const roll = random();
    const status = roll < 0.07 ? 'kelmadi' : roll < 0.17 ? 'kech' : 'keldi';
    const present = status !== 'kelmadi';
    const lateMinutes = 5 + Math.floor(random() * 30);
    const lessons = 3;
    const attended = present ? (random() < 0.12 ? 2 : 3) : 0;
    const lateToLesson = present && random() < 0.1 ? 1 : 0;
    const early = present && random() < 0.06 ? 1 : 0;
    const coat = present ? random() > 0.1 : null;
    const attention = present ? Math.round(55 + random() * 40) : null;
    const smoking = present && smokers.has(i) ? 1 : 0;

    if (present) came += 1;
    if (status === 'kech') late += 1;
    lessonsAttended += attended;
    lessonsTotal += lessons;
    lessonLate += lateToLesson;
    leftEarly += early;
    if (coat === false) noCoat += 1;
    if (attention !== null && attention < 60) lowAttention += 1;

    people.push({
      id: `namuna-${i + 1}`,
      full_name: `Namuna talaba ${String(i + 1).padStart(2, '0')}`,
      initials: 'NT',
      enrolled: true,
      cells: {
        davomat:
          status === 'keldi'
            ? cell('keldi', 'success', 'Keldi (namuna)')
            : status === 'kech'
              ? cell('kech', 'warning', 'Kech keldi (namuna)', random() < 0.5 ? 1 : 0)
              : cell('kelmadi', 'danger', 'Kelmadi (namuna)'),
        kechikish:
          status === 'kech' ? cell(`+${lateMinutes} daq`, 'warning', 'Kech keldi (namuna)') : present ? cell('0', 'neutral', 'O‘z vaqtida') : cell('—', 'neutral', ''),
        dars_qatnashish: cell(`${attended}/${lessons}`, attended === lessons ? 'success' : attended === 0 ? 'danger' : 'warning', 'Darsda (namuna)'),
        darsga_kech: cell(String(lateToLesson), lateToLesson ? 'danger' : 'neutral', 'Darsga kech kirish (namuna)', lateToLesson),
        darsdan_erta: cell(String(early), early ? 'danger' : 'neutral', 'Darsdan erta chiqish (namuna)', early),
        forma: coat === null ? cell('—', 'neutral', '') : coat ? cell('bor', 'success', 'Oq xalatda (namuna)') : cell('yo‘q', 'danger', 'Oq xalatsiz (namuna)', 1),
        chekish: present ? (smoking ? cell('1', 'danger', 'Chekish holati (namuna)', 1) : cell('yo‘q', 'neutral', 'Chekish qayd etilmagan')) : cell('—', 'neutral', ''),
        diqqat:
          attention === null
            ? cell('—', 'neutral', '')
            : cell(`${attention}%`, attention < 60 ? 'danger' : attention < 75 ? 'warning' : 'success', 'Diqqat balli (namuna)', attention < 60 ? 1 : 0),
      },
    });
  }

  const rate = pct(came, count);
  const attendRate = pct(lessonsAttended, lessonsTotal);
  const activity = Math.round(60 + random() * 30);
  const teacherOnTime = random() > 0.2;
  const criteria: GroupCriterion[] = [
    criterion('davomat', 7, 'Kelgan-kelmagani', `${rate}%`, rate >= 90 ? 'success' : rate >= 75 ? 'warning' : 'danger'),
    criterion('kechikish', 7, 'Kech kelganlar', String(late), late ? 'warning' : 'neutral'),
    criterion('dars_qatnashish', 7, 'Darsga kirgan talabalar', `${attendRate}%`, attendRate >= 90 ? 'success' : 'warning'),
    criterion('darsga_kech', 8, 'Darsga kech kirgan talabalar', String(lessonLate), lessonLate ? 'danger' : 'neutral'),
    criterion('darsdan_erta', 9, 'Darsdan erta chiqqan talabalar', String(leftEarly), leftEarly ? 'danger' : 'neutral'),
    criterion('forma', 10, 'Oq xalatsiz yurganlar', String(noCoat), noCoat ? 'danger' : 'neutral'),
    criterion('chekish', 15, 'Chekkanlar', String(smokers.size), 'danger'),
    criterion('diqqat', 19, 'Darsda diqqati past talabalar', String(lowAttention), lowAttention ? 'danger' : 'neutral'),
  ];
  return {
    group,
    period: { from: date, to: date, days: 1 },
    analysed: true,
    criteria,
    people,
    teacher: {
      activity,
      arrival: teacherOnTime ? 'o‘z vaqtida' : `+${3 + Math.floor(random() * 10)} daq`,
      arrivalTone: teacherOnTime ? 'success' : 'warning',
    },
  };
}
