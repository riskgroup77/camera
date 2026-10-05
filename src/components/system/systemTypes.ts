/** /api/system/* javoblari (camera-api/app/schemas/system.py) — sahifaga kerakli qismi. */
import type { RagThresholds } from '../../ui/rag';

export interface ResourceAlert {
  metric: string;
  level: 'warning' | 'critical';
  message: string;
}

export interface SystemResources {
  cpu: number;
  ram: number;
  disk: number;
  ffmpegProcessCount: number;
  streamReaderCount: number;
  alerts: ResourceAlert[];
}

export interface ConcurrencySlot {
  max: number;
  inUse: number;
  waiting?: number;
}

export interface SweepStatus {
  name: string;
  tier: string;
  intervalSeconds: number;
  runs: number;
  failures: number;
  running: boolean;
  lastFinishedAt: string | null;
  lastDurationSeconds: number;
  lastResult: number;
  lastError: string | null;
  lagging: boolean;
  paused?: boolean;
}

export interface SystemAiStatus {
  schedulerEnabled: boolean;
  schedulerPollSeconds?: number;
  /** Doimiy kuzatuvdagi kirish/chiqish kameralari. */
  entranceWatchers?: number;
  globalSweepConcurrency: number;
  faceInferenceConcurrency?: number;
  objectInferenceConcurrency?: number;
  criticalModules?: string[];
  standardModules?: string[];
  gpu: {
    cudaAvailable: boolean;
    onnxProviders?: string[];
    faceGpuEnabled?: boolean;
    faceGpuActive: boolean;
    objectGpuEnabled?: boolean;
    objectGpuActive: boolean;
    recommendation: string;
  };
  lastTick: {
    finishedAt?: string | null;
    durationSeconds: number;
    modulesRan: number;
    criticalRan: number;
    standardRan: number;
    skippedOverlap: boolean;
  };
  sweeps?: SweepStatus[];
  sweepSlots: ConcurrencySlot;
  faceInferenceGate: ConcurrencySlot & { waiting: number };
  embeddingSweepCacheTtlSeconds?: number;
}

export interface StreamShard {
  index: number;
  apiUrl?: string;
  reachable: boolean;
  pathCount: number;
  assignedCameras: number;
  error?: string | null;
}

export interface SystemStreamStatus {
  shardingEnabled: boolean;
  shardCount: number;
  faolCameras: number;
  registeredStreams: number;
  shards: StreamShard[];
  recommendation: string;
}

export interface SystemCameraNetwork {
  faolCameras: number;
  reachableCameras: number;
  offlineCameras: number;
  linkLocalIpCount: number;
  chronicOfflineCount: number;
  offlineAlertMinutes?: number;
  healthIntervalSeconds?: number;
  recentOfflineAlerts24h: number;
  lastSweep: {
    finishedAt?: string | null;
    durationSeconds: number;
    reachable: number;
    faolChecked: number;
    skippedOverlap: boolean;
  };
  recommendation: string;
}

/** Amal jurnali ustunlari (src/types AuditLogEntry bilan bir xil). */
export type AuditStatus = 'muvaffaqiyatli' | 'xatolik' | 'ogohlantirish';

/** Resurs chegaralari (foiz). Bitta joyda — kartadagi izoh bilan bir xil bo'lsin. */
export const RESOURCE_WARN_AT = 60;
export const RESOURCE_DANGER_AT = 80;

/** Foizli resurs → ohang: >80 xavf, >60 diqqat. */
export function resourceTone(value: number): 'success' | 'warning' | 'danger' {
  if (value > RESOURCE_DANGER_AT) return 'danger';
  if (value > RESOURCE_WARN_AT) return 'warning';
  return 'success';
}

/** Halqa rangining ma'nosi — rang yolg'iz signal bo'lib qolmasligi uchun. */
export const RESOURCE_TONE_LABEL: Record<'success' | 'warning' | 'danger', string> = {
  success: "Me'yorida",
  warning: 'Diqqat',
  danger: 'Yuqori',
};

export const RESOURCE_TONE_NOTE: Record<'success' | 'warning' | 'danger', string> = {
  success: `Yuklama ${RESOURCE_WARN_AT}% dan past — me'yorida`,
  warning: `Yuklama ${RESOURCE_WARN_AT}% dan yuqori — kuzatib turing`,
  danger: `Yuklama ${RESOURCE_DANGER_AT}% dan yuqori — video oqimlar va AI sekinlashishi mumkin`,
};

/** Fon vazifasi nomlari (texnik) → o'qiladigan nom. Noma'lumi o'zicha qoladi. */
const SWEEP_LABELS: Record<string, string> = {
  entrance_exit_attendance: 'Kirish/chiqish davomati',
  unified_face: 'Yuz tanish (umumiy)',
  attendance: 'Davomat',
  vision_sleep: 'Darsda uxlash',
  zone_entry: 'Taqiqlangan zona',
  teacher_punctuality: "O'qituvchi punktualligi",
  lesson_quality: 'Dars sifati',
  lesson_attendance: 'Dars davomatini yakunlash',
  absence_marking: '"Kelmadi" belgilash',
  module_suppression: 'Shovqinli signallarni cheklash',
  event_clips: 'Hodisa kliplari',
};

export function sweepLabel(name: string): string {
  return SWEEP_LABELS[name] ?? name.replace(/_/g, ' ');
}

/** Resurs foizi uchun svetofor chegarasi — `resourceTone` bilan bir xil.
 *  Teskari: KAM bo'lgani yaxshi, shuning uchun ok < warn. */
export const RESOURCE_RAG: RagThresholds = { ok: RESOURCE_WARN_AT, warn: RESOURCE_DANGER_AT };

/** Qamrov (oqim/kamera) ulushi uchun: 100% talab, 90% dan past — chora. */
export const COVERAGE_RAG: RagThresholds = { ok: 100, warn: 90 };
