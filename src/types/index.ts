export type CameraStatus = 'live' | 'offline';

/** Backenddagi GET /api/public/cameras javobiga mos — jismoniy kamera
 * (bino/zona/holat) haqidagi ma'lumot. Kameraning aynan qaysi fakultet/kurs/
 * guruh darsini ko'rsatib turgani haqida sxemada hech qanday bog'lanish
 * yo'q, shuning uchun bu yerda ham yo'q (ilgari mock ma'lumot buni
 * o'ylab topgan edi). */
export interface CameraFeed {
  id: string;
  name: string;
  building: string;
  zone: string;
  status: CameraStatus;
  /** Backend video-gateway tomonidan beriladigan HLS (.m3u8) yoki MP4/WebM manzil. Bo'sh bo'lsa — placeholder ko'rsatiladi. */
  streamUrl?: string;
}

/** Backenddagi GET /api/public/cameras/{id}/live-detection javobiga mos —
 * kadrda hozir topilgan bitta yuz haqida ma'lumot (chegara chizig'i,
 * agar tanilsa ismi, ko'z holati). */
export interface DetectedFace {
  bbox: [number, number, number, number];
  personName?: string | null;
  asleep: boolean;
}

export interface LiveDetectionResult {
  frameWidth: number;
  frameHeight: number;
  faces: DetectedFace[];
}

export interface AttendanceStats {
  totalStudents: number;
  present: number;
  absent: number;
  late: number;
  sleepIncidents: number;
  violations: number;
}

export interface TopStudent {
  id: string;
  name: string;
  group: string;
  attendanceRate: number;
}

export interface StudentStaffRecord {
  id: string;
  fullName: string;
  type: 'talaba' | 'xodim';
  faculty: string;
  groupOrPosition: string;
  biometricsStatus: 'tasdiqlangan' | 'kutilmoqda' | 'yoq';
  initials: string;
  biometricPhotoUrl?: string | null;
}

export interface Faculty {
  id: string;
  name: string;
  courseCount: number;
  studentCount: number;
}

export interface StudentGroup {
  id: string;
  name: string;
  faculty: string;
  course: number;
  studentCount: number;
}

export interface Building {
  id: string;
  name: string;
  cameraCount: number;
}

export interface CameraConfig {
  id: string;
  name: string;
  ip: string;
  port: number;
  rtspPath?: string | null;
  building: string;
  zone: string;
  resolution: string;
  fps: number | null;
  status: 'faol' | 'nofaol' | 'tamirda';
  /** Backend video-gateway tomonidan beriladigan HLS (.m3u8) yoki MP4/WebM manzil. Bo'sh bo'lsa — placeholder ko'rsatiladi. */
  streamUrl?: string;
  /** Kuzatilgan holat, sozlangan emas — `status` operator niyati
   * ("faol bo'lishi kerak"), bu esa app/jobs/camera_health.py'ning
   * so'nggi tekshiruvda kamerani haqiqatan topa olgan-olmaganligi. */
  isReachable: boolean;
}

export type AIModuleGroup = 'A' | 'B' | 'C' | 'D' | 'E' | 'F';

export interface AIModule {
  id: string;
  code: number;
  group: AIModuleGroup;
  name: string;
  description: string;
  method: string;
  accuracy: number;
  threshold: number;
  sensitivity: 'past' | "o'rta" | 'yuqori';
  cameraCount: number;
  active: boolean;
}

export interface Report {
  id: string;
  period: 'Kunlik' | 'Haftalik' | 'Oylik';
  periodLabel: string;
  generatedAt: string;
  source: 'rule' | 'llm';
  summary: string;
  body: string;
  stats: { label: string; value: string }[];
}

export interface AdminUser {
  id: string;
  name: string;
  login: string;
  initials: string;
  lastLogin: string;
  role: 'Super Admin' | 'Admin';
  email?: string | null;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  module: string;
  status: 'muvaffaqiyatli' | 'xatolik' | 'ogohlantirish';
  ip: string;
}

export type EventSeverity = 'past' | "o'rta" | 'yuqori';
export type EventStatus = 'yangi' | 'tasdiqlangan' | 'rad_etilgan';

export interface AIEvent {
  id: string;
  timestamp: string;
  cameraId: string;
  cameraName: string;
  building: string;
  moduleCode: number;
  moduleName: string;
  group: AIModuleGroup;
  confidence: number;
  severity: EventSeverity;
  status: EventStatus;
  personName?: string;
  reviewedBy?: string;
}

export type AttendanceDayStatus = 'keldi' | 'kelmadi' | 'kech_keldi' | 'dam_olish';

export interface AttendanceDay {
  date: string;
  status: AttendanceDayStatus;
  checkIn?: string;
  checkOut?: string;
  /** TT kriteriya 9 — backend qoidasi (app/routers/attendance.py) hisoblab beradi. */
  earlyLeave?: boolean;
}

export interface LessonSession {
  id: string;
  date: string;
  group: string;
  faculty: string;
  teacher: string;
  subject: string;
  attentionScore: number;
  sleepIncidents: number;
  teacherActivityScore: number;
  teacherOnTime: boolean;
}
