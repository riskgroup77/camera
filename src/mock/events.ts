import { cameraConfigs } from './admin';
import type { AIEvent, EventSeverity, EventStatus } from '../types';

interface EventTemplate {
  moduleCode: number;
  moduleName: string;
  group: AIEvent['group'];
  severity: EventSeverity;
  personPool?: string[];
}

const TEMPLATES: EventTemplate[] = [
  {
    moduleCode: 1,
    moduleName: 'Notanish/begona shaxsni aniqlash',
    group: 'A',
    severity: 'yuqori',
  },
  {
    moduleCode: 5,
    moduleName: 'Olomon zichligi anomaliyasi',
    group: 'A',
    severity: "o'rta",
  },
  {
    moduleCode: 6,
    moduleName: "Xodim/o'qituvchi davomati",
    group: 'B',
    severity: 'past',
    personPool: ['Toshmatov S.', 'Karimov B.', 'Nazarov K.', 'Yusupova N.'],
  },
  {
    moduleCode: 7,
    moduleName: 'Talaba davomati',
    group: 'B',
    severity: 'past',
    personPool: ['Sharipova F.', 'Qodirov A.', 'Xoliqov R.', 'Sultonova M.'],
  },
  {
    moduleCode: 8,
    moduleName: 'Darsga kechikish',
    group: 'B',
    severity: "o'rta",
    personPool: ['Rashidov U.', 'Normatova X.', 'Mirzayev T.', 'Botirov J.'],
  },
  {
    moduleCode: 10,
    moduleName: 'Oq xalat kiyilganligi',
    group: 'C',
    severity: 'past',
    personPool: ['Holiqova S.', 'Sharipova F.', 'Qodirov A.'],
  },
  {
    moduleCode: 11,
    moduleName: 'Bosh kiyim (kalpakcha) borligi',
    group: 'C',
    severity: 'past',
    personPool: ['Xoliqov R.', 'Sultonova M.'],
  },
];

function seededPick<T>(arr: T[], seed: number): T {
  return arr[seed % arr.length];
}

function statusForIndex(i: number): EventStatus {
  const m = i % 5;
  if (m === 0) return 'tasdiqlangan';
  if (m === 1) return 'rad_etilgan';
  return 'yangi';
}

const REVIEWERS = ['Jamshid Alimov', 'Nodira Yusupova', 'Behzod Karimov'];

export const aiEvents: AIEvent[] = Array.from({ length: 42 }, (_, i) => {
  const n = i + 1;
  const template = seededPick(TEMPLATES, n);
  const camera = seededPick(cameraConfigs, n + 2);
  const hour = String(23 - (n % 24)).padStart(2, '0');
  const minute = String((n * 11) % 60).padStart(2, '0');
  const status = statusForIndex(n);
  const confidence = 68 + ((n * 7) % 31);

  return {
    id: `ev-${String(n).padStart(3, '0')}`,
    timestamp: `2026-07-30 ${hour}:${minute}`,
    cameraId: camera.id,
    cameraName: camera.name,
    building: camera.building,
    moduleCode: template.moduleCode,
    moduleName: template.moduleName,
    group: template.group,
    confidence,
    severity: template.severity,
    status,
    personName: template.personPool ? seededPick(template.personPool, n) : undefined,
    reviewedBy: status !== 'yangi' ? seededPick(REVIEWERS, n) : undefined,
  };
});
