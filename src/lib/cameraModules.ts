import type { AIModule, AIModuleGroup, CameraConfig, CameraModuleOption } from '../types';

/** Modul shu kamerada ishlaydimi (exclude-list + global active + has_detector). */
export function isModuleEnabledOnCamera(
  module: Pick<AIModule | CameraModuleOption, 'code' | 'active' | 'hasDetector'>,
  camera: Pick<CameraConfig, 'excludedModuleCodes'>,
): boolean {
  if (!module.active || !module.hasDetector) return false;
  const excluded = camera.excludedModuleCodes ?? [];
  return !excluded.includes(module.code);
}

export function countEnabledModulesOnCamera(
  modules: Array<Pick<AIModule | CameraModuleOption, 'code' | 'active' | 'hasDetector'>>,
  camera: Pick<CameraConfig, 'excludedModuleCodes'>,
): { enabled: number; total: number; runnable: number } {
  const runnable = modules.filter((m) => m.hasDetector);
  const enabled = runnable.filter((m) => isModuleEnabledOnCamera(m, camera)).length;
  return { enabled, total: modules.length, runnable: runnable.length };
}

export function formatModuleSummary(
  modules: Array<Pick<AIModule | CameraModuleOption, 'code' | 'active' | 'hasDetector'>>,
  camera: Pick<CameraConfig, 'excludedModuleCodes'>,
): string {
  const { enabled, runnable } = countEnabledModulesOnCamera(modules, camera);
  const excludedCount = camera.excludedModuleCodes?.length ?? 0;
  if (excludedCount === 0) return `${enabled}/${runnable} modul`;
  return `${enabled}/${runnable} modul (${excludedCount} o'chirilgan)`;
}

// Buyurtmachi ro'yxati (2026-10-06): 1, 6, 7, 8, 9, 10, 15, 19, 21, 22.
const GROUP_CODES: Record<AIModuleGroup, number[]> = {
  A: [1],
  B: [6, 7, 8, 9],
  C: [10],
  D: [15],
  E: [19, 21, 22],
  F: [],
};

export type ModulePresetId = 'all' | 'entrance' | 'indoor' | 'outdoor' | 'security';

export const MODULE_PRESETS: { id: ModulePresetId; label: string; description: string }[] = [
  {
    id: 'all',
    label: 'Hammasi yoqilgan',
    description: 'Barcha faol modullar shu kamerada ishlaydi',
  },
  {
    id: 'entrance',
    label: 'Kirish / koridor',
    description: 'Davomat, erta ketish, begona shaxs, oq xalat, chekish — dars modullarisiz',
  },
  {
    id: 'indoor',
    label: 'Ichki xona / auditoriya',
    description: 'Dars modullari, oq xalat, chekish — begona shaxs va kirish davomatisiz',
  },
  {
    id: 'outdoor',
    label: 'Hovli / tashqi',
    description: 'Begona shaxs va chekish — dars modullarisiz',
  },
  {
    id: 'security',
    label: 'Faqat begona shaxs (A)',
    description: 'Faqat begona shaxsni aniqlash yoqilgan',
  },
];

export function presetExcludedCodes(preset: ModulePresetId, allCodes: number[]): Set<number> {
  const all = new Set(allCodes);
  if (preset === 'all') return new Set();

  const keep = new Set<number>();
  if (preset === 'entrance') {
    [1, 6, 7, 9, 10, 15].forEach((c) => keep.add(c));
  } else if (preset === 'indoor') {
    [8, 9, 10, 15, 19, 21, 22].forEach((c) => keep.add(c));
  } else if (preset === 'outdoor') {
    [1, 15].forEach((c) => keep.add(c));
  } else if (preset === 'security') {
    GROUP_CODES.A.forEach((c) => keep.add(c));
  }

  const excluded = new Set<number>();
  for (const code of all) {
    if (!keep.has(code)) excluded.add(code);
  }
  return excluded;
}

export function toggleGroupExclusion(
  excluded: Set<number>,
  group: AIModuleGroup,
  enableGroup: boolean,
  modules: Array<Pick<CameraModuleOption, 'code' | 'group' | 'hasDetector'>>,
): Set<number> {
  const next = new Set(excluded);
  for (const m of modules) {
    if (m.group !== group || !m.hasDetector) continue;
    if (enableGroup) next.delete(m.code);
    else next.add(m.code);
  }
  return next;
}
