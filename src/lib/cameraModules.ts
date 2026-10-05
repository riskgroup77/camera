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

const GROUP_CODES: Record<AIModuleGroup, number[]> = {
  A: [1, 2, 3, 4, 5],
  B: [6, 7, 8, 9],
  C: [10, 11, 12, 13],
  D: [14, 15, 16, 17, 18],
  E: [19, 20, 21, 22],
  F: [23, 24, 25],
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
    description: 'Davomat, begona shaxs, uxlab qolish — auditoriya modullarisiz',
  },
  {
    id: 'indoor',
    label: 'Ichki xona / auditoriya',
    description: 'Transport (hovli) moduli o‘chirilgan',
  },
  {
    id: 'outdoor',
    label: 'Hovli / tashqi',
    description: 'Imtihon va dars sifati modullari o‘chirilgan',
  },
  {
    id: 'security',
    label: 'Faqat xavfsizlik (A)',
    description: 'Faqat A-toifa kriteriyalari yoqilgan',
  },
];

export function presetExcludedCodes(preset: ModulePresetId, allCodes: number[]): Set<number> {
  const all = new Set(allCodes);
  if (preset === 'all') return new Set();

  const keep = new Set<number>();
  if (preset === 'entrance') {
    [1, 2, 3, 4, 6, 7, 20].forEach((c) => keep.add(c));
  } else if (preset === 'indoor') {
    allCodes.filter((c) => c !== 25).forEach((c) => keep.add(c));
  } else if (preset === 'outdoor') {
    allCodes.filter((c) => ![16, 19, 21, 22].includes(c)).forEach((c) => keep.add(c));
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
